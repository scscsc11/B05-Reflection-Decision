"""Exercise evidence filtering, version history, and compatibility with older knowledge."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src import experience_store as knowledge


def entry(label="materials", status="verified", conditions=("download-failure", "login-works")):
    return {
        "task": "support-tickets", "domain": "campus-support-demo", "topic": "course-materials",
        "conditions": list(conditions), "case_label": label, "problem": "Download fails",
        "lesson": "Use the primary symptom.", "applies_when": "The session already works.",
        "status": status, "expected_label": label if status == "verified" else None,
        "source": "simulated_gateway",
    }


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "knowledge.sqlite3"

    def test_conflicts_use_explicit_conditions_and_evidence(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "a", entry())
            knowledge.save_lesson(db, "scope", "b", entry("account", "unverified"))
            knowledge.save_lesson(db, "scope", "c", entry("schedule", "rejected"))
            knowledge.save_lesson(db, "scope", "d", entry("other", "verified", conditions=("login-works",)))
            features = ["login-works", "download-failure", "pdf"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "next")
            self.assertEqual([hit["case_id"] for hit in hits], ["a"])
            self.assertEqual([row["handling"] for row in conflicts], ["prefer_verified", "prefer_dominant"])
            self.assertEqual(conflicts[0]["preferred_label"], "materials")
            knowledge.save_lesson(db, "scope", "b", entry("account", "verified"))
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "d")
            self.assertEqual(hits, [])
            self.assertEqual([row["handling"] for row in conflicts], ["withhold"])

    def test_incomparable_applicable_conditions_withhold_conflicting_labels(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "account", entry("account", conditions=("login-works",)))
            knowledge.save_lesson(db, "scope", "download", entry(conditions=("download-failure", "pdf")))
            features = ["login-works", "download-failure", "pdf"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "new")
            self.assertEqual(hits, [])
            self.assertEqual(conflicts[0]["scope"], "applicable")
            self.assertEqual(conflicts[0]["handling"], "withhold")

    def test_exact_ambiguity_is_not_hidden_by_a_broad_fallback(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "a", entry("materials"))
            knowledge.save_lesson(db, "scope", "b", entry("account"))
            knowledge.save_lesson(db, "scope", "broad", entry("materials", conditions=("login-works",)))
            features = ["login-works", "download-failure"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "new")
            self.assertEqual(hits, [])
            self.assertEqual([item["handling"] for item in conflicts], ["withhold", "withhold"])

    def test_repeating_same_entry_does_not_create_a_revision(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry())["revision"], 1)
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry())["action"], "unchanged")
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry("other"))["revision"], 2)
            history = db.execute("SELECT revision, case_label FROM knowledge_versions ORDER BY revision")
            self.assertEqual([tuple(row) for row in history], [(1, "materials"), (2, "other")])
            hits, _ = knowledge.retrieve_lessons(
                db, "scope", "course-materials", ["login-works", "download-failure"], "a"
            )
            self.assertEqual(hits, [])

    def test_provenance_is_preserved_per_revision(self):
        first = {
            "initial_label": "account", "source_round": 1, "selected_round": 1, "final_label": "materials",
        }
        second = first | {"source_round": 2, "selected_round": 2}
        with closing(knowledge.open_store(self.path)) as db, db:
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry() | {"provenance": first})["revision"], 1)
            update = knowledge.save_lesson(db, "scope", "a", entry() | {"provenance": second})
            self.assertEqual((update["action"], update["revision"]), ("updated", 2))
            repeated = knowledge.save_lesson(db, "scope", "a", entry() | {"provenance": second})
            self.assertEqual((repeated["action"], repeated["revision"]), ("unchanged", 2))
            without_provenance = knowledge.save_lesson(db, "scope", "a", entry())
            self.assertEqual((without_provenance["action"], without_provenance["revision"]), ("unchanged", 2))

        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            history = db.execute("SELECT revision, provenance FROM knowledge_versions ORDER BY revision")
            self.assertEqual([(row["revision"], json.loads(row["provenance"])) for row in history],
                             [(1, first), (2, second)])
            latest = knowledge.latest_lessons(db, "scope")
            self.assertEqual(latest, [{"case_id": "a", "revision": 2, **entry(), "provenance": second}])
            hits, _ = knowledge.retrieve_lessons(db, "scope", "course-materials", entry()["conditions"], "b")
            self.assertEqual([hit["revision"] for hit in hits], [2])
            self.assertNotIn("provenance", hits[0])

    def test_provenance_must_match_the_selected_decision(self):
        record = entry() | {"provenance": {
            "initial_label": "account", "source_round": 1, "selected_round": 0, "final_label": "materials",
        }}
        with self.assertRaisesRegex(ValueError, "conflicts with the selected decision"):
            knowledge.plan_lesson(None, record)
        record["provenance"] |= {"selected_round": 1, "final_label": "schedule"}
        with self.assertRaisesRegex(ValueError, "conflicts with the selected decision"):
            knowledge.plan_lesson(None, record)

    def test_previous_schema_read_only_and_writable_compatibility(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE knowledge_versions (
                    scope TEXT NOT NULL, case_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    task TEXT NOT NULL, domain TEXT NOT NULL, topic TEXT NOT NULL, conditions TEXT NOT NULL,
                    case_label TEXT NOT NULL, problem TEXT NOT NULL, lesson TEXT NOT NULL,
                    applies_when TEXT NOT NULL, status TEXT NOT NULL, expected_label TEXT,
                    source TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, case_id, revision)
                );
                INSERT INTO knowledge_versions VALUES (
                    'scope', 'a', 1, 'support-tickets', 'campus-support-demo', 'course-materials',
                    '["download-failure", "login-works"]', 'materials', 'Download fails',
                    'Use the primary symptom.', 'The session already works.', 'verified',
                    'materials', 'simulated_gateway', '2026-11-20'
                );
            """)
        original = self.path.read_bytes()
        previous = [{"case_id": "a", "revision": 1, **entry()}]
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            self.assertEqual(knowledge.latest_lessons(db, "scope"), previous)
        self.assertEqual(self.path.read_bytes(), original)

        provenance = {
            "initial_label": "account", "source_round": 1, "selected_round": 1, "final_label": "materials",
        }
        with closing(knowledge.open_store(self.path)) as db, db:
            self.assertEqual(knowledge.latest_lessons(db, "scope"), previous)
            update = knowledge.save_lesson(db, "scope", "a", entry() | {"provenance": provenance})
            self.assertEqual((update["action"], update["revision"]), ("updated", 2))
            history = db.execute("SELECT revision, provenance FROM knowledge_versions ORDER BY revision")
            self.assertEqual([(row["revision"], row["provenance"] is None) for row in history],
                             [(1, True), (2, False)])

        with closing(knowledge.open_store(self.path)) as db:
            self.assertEqual(knowledge.latest_lessons(db, "scope"),
                             [{"case_id": "a", "revision": 2, **entry(), "provenance": provenance}])

    def test_legacy_rows_are_imported_once_as_unverified(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE lessons (scope TEXT, case_id TEXT, revision INTEGER, "
                "topic TEXT, label TEXT, lesson TEXT, updated_at TEXT)"
            )
            db.execute(
                "INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("old-scope", "previous", 2, "course-materials", "materials", "Old advice", "2026-11-20"),
            )
        for _ in range(2):
            with closing(knowledge.open_store(self.path)) as db:
                hits = knowledge.latest_lessons(db, "old-scope")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["status"], "unverified")
                self.assertEqual(hits[0]["source"], "legacy")
                self.assertEqual(hits[0]["revision"], 2)
                self.assertEqual(knowledge.latest_lessons(db, "new-scope"), [])
