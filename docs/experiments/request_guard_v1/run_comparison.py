"""Compare two knowledge-match policies with fixed replies on synthetic campus tickets."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2] / "dev"))

from src import reflection, scene_io, score_benchmark

RESULT = "benchmark_results.json"
INITIALS = dict(zip(
    ("req-h01", "req-h02", "req-h03", "req-h04", "req-h05", "req-h06", "req-h07"),
    ("schedule", "other", "other", "materials", "schedule", "materials", "other"),
    strict=True,
))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


class Model:
    endpoint = "in-process://campus-request-features"
    model = "request-policy-fixture"
    use_json_schema = False
    timeout = 30.0

    def __init__(self, seed_labels=None):
        self.seed_labels = seed_labels
        self.requests = []

    def complete(self, stage, instructions, data, schema, *, budget):
        key = data["case"]["id"]
        prior = data.get("prior_lessons", [])
        if self.seed_labels is not None:
            label = self.seed_labels[key]
        elif stage == "initial":
            label = INITIALS[key]
        else:
            evidence = {row["case_label"] for row in prior if row["status"] == "verified"}
            label = evidence.pop() if len(evidence) == 1 else data["previous"]["label"]
        self.requests.append({
            "case_id": key, "stage": stage, "round": data.get("round", 0),
            "sent_lessons": prior, "feedback": data.get("feedback"), "reply_label": label,
        })
        if stage == "initial":
            return {"label": label, "reason": "预设初判，用于核验条件复核。"}
        return {
            "label": label, "review": "替身保留上轮类别，或跟随唯一已验证历史。",
            "knowledge": {"problem": "判断工单主诉。", "lesson": "检查历史条件能否用于该工单。",
                          "applies_when": "工单记录包含相关条件。"},
        }


def main():
    manifest = scene_io.read_json(ROOT / "manifest.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="new directory for comparison outputs")
    work = parser.parse_args().run_dir.resolve()
    if work.is_relative_to(ROOT):
        parser.error("Choose a run directory outside the frozen input package.")
    work.mkdir(parents=True)
    offline = ROOT / "offline"
    reads = []
    phase = "inference"

    def audit(event, args):
        if event.startswith("socket."):
            raise AssertionError(f"Unexpected network operation: {event}")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.is_relative_to(offline):
                reads.append({"phase": phase, "file": path.name})
                if phase != "score":
                    raise AssertionError(f"Premature offline file open: {path}")

    sys.addaudithook(audit)
    for name in ("seed_input/benchmark.json", "seed_input/answers.json", "heldout_input/benchmark.json"):
        if digest(ROOT / name) != manifest["sha256"][name]:
            raise ValueError(f"Frozen input was modified: {name}")
    seed_inputs = ROOT / "seed_input"
    heldout = ROOT / "heldout_input"
    seed_labels = scene_io.read_json(seed_inputs / "answers.json")
    seed_db = work / "knowledge.sqlite3"
    start = work / "initial" / "norethink" / RESULT
    shared = {"review_rounds": manifest["review_rounds"], "time_budget": manifest["time_budget_seconds"]}
    models = {name: Model() for name in ("initial", "cold", "warm", "baseline", "request_required")}
    with patch.object(reflection.ModelClient, "from_env", side_effect=AssertionError("Real gateway setup attempted")):
        reflection.run(seed_inputs, work / "seed", seed_db, use_history=False,
                       in_process_model=Model(seed_labels), **shared)
        seed_digest = digest(seed_db)
        with patch.object(reflection, "load_answers", side_effect=AssertionError("Blind answer loading attempted")):
            reflection.run(heldout, work / "initial", None, review_rounds=0, blind=True,
                           time_budget=shared["time_budget"], in_process_model=models["initial"])
            for name in ("cold", "warm", "baseline", "request_required"):
                reflection.run(
                    heldout, work / name, seed_db if name != "cold" else None, blind=True, initial_results=start,
                    use_history=name != "cold", guard_review=name in ("baseline", "request_required"),
                    require_request_feature=name == "request_required", in_process_model=models[name], **shared,
                )
                assert digest(seed_db) == seed_digest

    assert not reads
    raw = {path: digest(path) for path in work.glob("*/*/benchmark_results.json")}
    phase = "score"
    scores = {}
    for name in ("baseline", "request_required"):
        output = work / f"{name}_score.json"
        assert score_benchmark.main([
            "--initial", str(start), "--without-history", str(work / "cold" / "rethink" / RESULT),
            "--with-history", str(work / "warm" / "rethink" / RESULT),
            "--guarded", str(work / name / "rethink" / RESULT), "--answers", str(offline / "answers.json"),
            "--answers-sha256", manifest["sha256"]["offline/answers.json"], "--output", str(output),
        ]) == 0
        scores[name] = scene_io.read_json(output)
    assert raw == {path: digest(path) for path in raw}
    assert reads == [{"phase": "score", "file": "answers.json"}] * 2
    assert scores["baseline"]["initial_fingerprint"] == scores["request_required"]["initial_fingerprint"]
    assert scores["request_required"]["guard_match_policy"] == reflection.GUARD_REQUEST_POLICY
    oracles = scene_io.read_json(
        offline / "scenarios.json", expected_sha256=manifest["sha256"]["offline/scenarios.json"],
    )["cases"]
    paired = {}
    for key, oracle in oracles.items():
        checks = {}
        for name, score in scores.items():
            initial = score["cases"][key]["initial"]
            decision = score["cases"][key]["review_with_guard"]
            calls = [call for call in models[name].requests if call["case_id"] == key]
            actual = {"trigger": bool(calls), "final_label": decision["label"],
                      "comparison": decision["change_from_initial"]}
            assert initial["label"] == oracle["initial_label"]
            assert actual == oracle[name], (key, name, actual)
            checks[name] = actual | {"model_calls": len(calls), "guard": decision["review_gate"]}
        paired[key] = {"role": oracle["role"], "initial_label": oracle["initial_label"], **checks}

    write(work / "requests.json", {name: model.requests for name, model in models.items()})
    write(work / "comparison.json", {
        "source": "in_process_stub", "scope": "Scripted replies for rule and evaluation verification",
        "seed_count": len(seed_labels), "heldout_count": len(paired), "seed_sha256": seed_digest,
        "initial_fingerprint": scores["baseline"]["initial_fingerprint"], "offline_reads": reads,
        "counts": {name: score["counts"]["review_with_guard"] for name, score in scores.items()},
        "paired_cases": paired,
    })
    print(work / "comparison.json")


if __name__ == "__main__":
    main()
