"""Versioned SQLite knowledge with condition-based retrieval and conflict checks."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RETRIEVAL_POLICY = "knowledge-applicability-v2"
PROVENANCE_SCHEMA = "knowledge-provenance-v1"

FIELDS = (
    "task", "domain", "topic", "conditions", "case_label", "problem", "lesson",
    "applies_when", "status", "expected_label", "source",
)


def has_provenance(db: sqlite3.Connection) -> bool:
    return any(row[1] == "provenance" for row in db.execute("PRAGMA table_info(knowledge_versions)"))


def decode_lesson(row: sqlite3.Row) -> dict:
    record = dict(row)
    lesson = {key: record[key] for key in ("case_id", "revision", *FIELDS)}
    lesson["conditions"] = json.loads(lesson["conditions"])
    provenance = record.get("provenance")
    if provenance is not None:
        lesson["provenance"] = json.loads(provenance)
    return lesson


def open_store(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_versions (
                    scope TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    task TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    conditions TEXT NOT NULL,
                    case_label TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    applies_when TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('verified', 'unverified', 'rejected')),
                    expected_label TEXT,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    provenance TEXT,
                    PRIMARY KEY (scope, case_id, revision)
                )
            """)
            if not has_provenance(db):
                db.execute("ALTER TABLE knowledge_versions ADD COLUMN provenance TEXT")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons'").fetchone():
                # Keep old scopes and provenance separate from new experiments.
                db.execute("""
                    INSERT OR IGNORE INTO knowledge_versions (
                        scope, case_id, revision, task, domain, topic, conditions, case_label,
                        problem, lesson, applies_when, status, expected_label, source, updated_at
                    )
                    SELECT scope, case_id, revision, 'legacy', '', topic, '[]', label,
                           '', lesson, '', 'unverified', NULL, 'legacy', updated_at
                    FROM lessons
                """)
    except sqlite3.Error:
        db.close()
        raise
    return db


def plan_lesson(current: dict | None, entry: dict) -> dict:
    """Compute the revision of an update against the current knowledge snapshot."""
    provenance = entry.get("provenance")
    if provenance is not None:
        if (
            not isinstance(provenance, dict)
            or provenance.keys() != {"initial_label", "source_round", "selected_round", "final_label"}
            or any(not isinstance(provenance[key], str) or not provenance[key].strip()
                   for key in ("initial_label", "final_label"))
            or type(provenance["source_round"]) is not int or provenance["source_round"] < 1
            or type(provenance["selected_round"]) is not int or provenance["selected_round"] < 0
        ):
            raise ValueError("Invalid review provenance.")
        selected_round = provenance["selected_round"]
        final_label = provenance["final_label"]
        if (
            (selected_round == 0 and final_label != provenance["initial_label"])
            or (selected_round == provenance["source_round"] and final_label != entry["case_label"])
        ):
            raise ValueError("Review provenance conflicts with the selected decision.")
    if current is None:
        return {"action": "inserted", "revision": 1, "status": entry["status"]}
    same_provenance = provenance is None or current.get("provenance") == provenance
    same = same_provenance and all(
        set(current[key]) == set(entry[key]) if key == "conditions" else current[key] == entry[key]
        for key in FIELDS
    )
    return {
        "action": "unchanged" if same else "updated",
        "revision": current["revision"] if same else current["revision"] + 1,
        "status": entry["status"],
    }


def save_lesson(db: sqlite3.Connection, scope: str, case_id: str, entry: dict) -> dict:
    """Save a new revision only when the structured record changes."""
    row = db.execute("""
        SELECT * FROM knowledge_versions
        WHERE scope = ? AND case_id = ?
        ORDER BY revision DESC LIMIT 1
    """, (scope, case_id)).fetchone()
    current = decode_lesson(row) if row is not None else None
    update = plan_lesson(current, entry)
    if update["action"] == "unchanged":
        return update

    payload = {key: entry[key] for key in FIELDS}
    payload["conditions"] = json.dumps(sorted(set(payload["conditions"])), ensure_ascii=False)
    provenance = entry.get("provenance")
    db.execute("""
        INSERT INTO knowledge_versions (
            scope, case_id, revision, task, domain, topic, conditions, case_label, problem,
            lesson, applies_when, status, expected_label, source, updated_at, provenance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        scope, case_id, update["revision"], *(payload[key] for key in FIELDS),
        datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        json.dumps(provenance, ensure_ascii=False, sort_keys=True) if provenance is not None else None,
    ))
    return update


def latest_lessons(db: sqlite3.Connection, scope: str) -> list[dict]:
    # The decoder handles seeds created before provenance was stored.
    rows = db.execute("""
        SELECT k.*
        FROM knowledge_versions AS k
        JOIN (
            SELECT scope, case_id, MAX(revision) AS revision
            FROM knowledge_versions WHERE scope = ? GROUP BY scope, case_id
        ) AS latest USING (scope, case_id, revision)
        ORDER BY k.updated_at DESC, k.case_id
    """, (scope,))
    return [decode_lesson(row) for row in rows]


def detect_conflicts(lessons: list[dict]) -> list[dict]:
    """Flag differing labels under the same explicit, nonempty conditions."""
    groups = {}
    for lesson in lessons:
        if lesson["status"] != "rejected" and lesson["conditions"]:
            key = (lesson["topic"], tuple(sorted(set(lesson["conditions"]))))
            groups.setdefault(key, []).append(lesson)

    conflicts = []
    for (topic, conditions), entries in groups.items():
        labels = sorted({entry["case_label"] for entry in entries})
        if len(labels) < 2:
            continue
        verified = {entry["case_label"] for entry in entries if entry["status"] == "verified"}
        preferred = next(iter(verified)) if len(verified) == 1 else None
        conflicts.append({
            "topic": topic,
            "conditions": list(conditions),
            "labels": labels,
            "case_ids": sorted(entry["case_id"] for entry in entries),
            "preferred_label": preferred,
            "handling": "prefer_verified" if preferred is not None else "withhold",
        })
    return conflicts


def retrieve_lessons(
    db: sqlite3.Connection, scope: str, topic: str, conditions: list[str], case_id: str,
) -> tuple[list[dict], list[dict]]:
    return select_lessons(latest_lessons(db, scope), topic, conditions, case_id)


def select_lessons(
    recent: list[dict], topic: str, conditions: list[str], case_id: str,
) -> tuple[list[dict], list[dict]]:
    """Filter applicable evidence by verification and inclusion of conditions."""
    current_conditions = set(conditions)
    matches = [
        entry for entry in recent
        if entry["case_id"] != case_id and entry["topic"] == topic
        and entry["status"] != "rejected" and set(entry["conditions"]) <= current_conditions
    ]
    conflicts = detect_conflicts(matches)
    labels = {entry["case_label"] for entry in matches}
    kept = matches
    if len(labels) > 1:
        # More specific evidence can displace broader evidence only with
        # at least the same verification status. Incomparable evidence ties.
        ranks = [(entry["status"] == "verified", frozenset(entry["conditions"])) for entry in matches]
        strongest = {
            entry["case_label"]
            for entry, (verified, features) in zip(matches, ranks)
            if not any(
                other_verified >= verified and other_features >= features
                and (other_verified, other_features) != (verified, features)
                for other_verified, other_features in ranks
            )
        }
        preferred = next(iter(strongest)) if len(strongest) == 1 else None
        kept = [entry for entry in matches if entry["case_label"] == preferred]
        if len({features for _, features in ranks}) > 1:
            conflicts.append({
                "topic": topic, "conditions": sorted(current_conditions), "scope": "applicable",
                "labels": sorted(labels), "case_ids": sorted(entry["case_id"] for entry in matches),
                "preferred_label": preferred,
                "handling": "prefer_dominant" if preferred is not None else "withhold",
            })
    kept.sort(key=lambda entry: (entry["status"] != "verified", -len(entry["conditions"])))
    fields = ("case_id", "revision", "topic", "conditions", "case_label", "problem",
              "lesson", "applies_when", "status", "source")
    return [{key: entry[key] for key in fields} for entry in kept[:3]], conflicts
