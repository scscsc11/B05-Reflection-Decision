"""Run the frozen campus-ticket guard comparison using a bounded personal gateway."""

import argparse
import io
import json
import math
import os
import sqlite3
import sys
from contextlib import closing
from copy import deepcopy
from getpass import GetPassWarning, getpass
from pathlib import Path
from types import SimpleNamespace
from warnings import catch_warnings, simplefilter

from run_comparison import ROOT, RESULT, Model, digest, reflection, scene_io, score_benchmark, write
from personal_stream import PersonalStreamClient
from src.llm_client import ModelClient, ModelError

INITIAL_CAP = 96
REVIEW_CAP = 160
ARMS = (("request_required", True), ("baseline", False))


def frozen_file(manifest, name):
    return scene_io.read_json(ROOT / name, expected_sha256=manifest["sha256"][name])


def gateway_fingerprint(model):
    profile = {key: value for key, value in model.profile.items() if key != "max_requests"}
    return reflection.fingerprint([model.endpoint, model.model, model.use_json_schema, model.timeout, profile])


def prepare(manifest, ids):
    seed = frozen_file(manifest, "seed_input/benchmark.json")
    heldout = frozen_file(manifest, "heldout_input/benchmark.json")
    answers = frozen_file(manifest, "seed_input/answers.json")
    if (seed["domain"], seed["labels"]) != (heldout["domain"], heldout["labels"]):
        raise ValueError("Seed and held-out benchmark definitions differ.")
    cases_by_id = {row["id"]: row for row in heldout["cases"]}
    if len(set(ids)) != len(ids) or any(case_id not in cases_by_id for case_id in ids):
        raise ValueError("Choose distinct case IDs from the frozen held-out benchmark.")
    if {row["id"] for row in seed["cases"]} != answers.keys() or set(ids) & answers.keys():
        raise ValueError("Seed identity or reference coverage is inconsistent.")
    cases = [cases_by_id[case_id] for case_id in ids]
    lessons = []
    for row in seed["cases"]:
        label = answers[row["id"]]
        if label not in seed["labels"]:
            raise ValueError("A seed label is outside the benchmark categories.")
        lessons.append({
            "case_id": row["id"], "revision": 1,
            "task": reflection.TASK, "domain": seed["domain"], "topic": row["topic"],
            "conditions": row["features"], "case_label": label, "expected_label": label,
            "problem": "识别工单主诉", "lesson": "按主诉核对工单类别", "applies_when": "工单条件和主诉匹配",
            "status": "verified", "source": "synthetic_reference_fixture",
        })
    return heldout | {"cases": cases}, lessons


def load_learned_seed(directory, dataset, fixture_lessons, *, source=None):
    report_path = directory / "seed_run.json"
    report = scene_io.read_json(report_path)
    seed_path = directory / "seed.sqlite3"
    if (
        report.get("passed") is not True or report.get("source") not in {"personal_gateway", "in_process_stub"}
        or (source is not None and report["source"] != source)
        or report.get("manifest_sha256") != digest(ROOT / "manifest.json")
        or report.get("seed_sha256") != digest(seed_path)
    ):
        raise ValueError("The learned seed does not match this benchmark or gateway source.")
    scope = reflection.fingerprint([reflection.TASK, dataset["domain"], dataset["labels"], report["source"]])
    if report.get("scope") != scope:
        raise ValueError("The learned seed scope differs from the held-out benchmark.")
    lessons = reflection.blind_seed(seed_path, scope, {case["id"] for case in dataset["cases"]})
    ids = report.get("seed_case_ids")
    if (
        not isinstance(ids, list) or any(not isinstance(case_id, str) for case_id in ids)
        or len(lessons) != len(ids) or {row["case_id"] for row in lessons} != set(ids)
    ):
        raise ValueError("Learned seed case IDs do not match the seed report.")
    expected = {row["case_id"]: row for row in fixture_lessons}
    for row in lessons:
        reference = expected.get(row["case_id"])
        if (
            reference is None or row.get("topic") != reference["topic"]
            or row.get("conditions") != reference["conditions"]
            or row.get("expected_label") != reference["expected_label"]
            or row.get("case_label") not in dataset["labels"] or row.get("source") != report["source"]
        ):
            raise ValueError("A learned record does not match its frozen seed case.")
        status = "verified" if row["case_label"] == reference["expected_label"] else "rejected"
        if row.get("status") != status or not isinstance(row.get("provenance"), dict):
            raise ValueError("A learned record is missing valid review provenance.")
    return lessons, (seed_path, report)


def request_bound(dataset, lessons, rounds, *, reuse_initial=False):
    labels = dataset["labels"]
    initials = 0 if reuse_initial else len(dataset["cases"])
    bounds = {arm: 0 for arm, _ in ARMS}
    reviews = 0
    for case in dataset["cases"]:
        history, _ = reflection.experience_store.select_lessons(
            lessons, case["topic"], case["features"], case["id"],
        )
        eligible = set()
        distinct_contexts = 0
        for label in labels:
            contexts = set()
            for arm, requires_request in ARMS:
                gate = reflection.verified_review_gate(
                    case, labels, {"label": label}, history, require_request_feature=requires_request,
                )
                if gate["action"] == "review":
                    eligible.add(arm)
                    contexts.add(reflection.fingerprint(reflection.guarded_prompt_lessons(history, gate)))
            distinct_contexts = max(distinct_contexts, len(contexts))
        for arm in eligible:
            bounds[arm] += rounds
        reviews += rounds * distinct_contexts
    return {
        "initial_requests": initials, "review_requests_by_arm": bounds, "distinct_review_requests": reviews,
        "max_requests": initials + reviews,
        "requested_output_token_cap": initials * INITIAL_CAP + reviews * REVIEW_CAP,
    }


class PairedStreamClient(PersonalStreamClient):
    """Use one sampled reply for identical review requests within a comparison."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.arm = "initial"
        self.reused_reviews = []
        self._review_responses = {}

    def complete(self, stage, instructions, data, schema, *, budget=None):
        if stage != "review":
            return super().complete(stage, instructions, data, schema, budget=budget)
        key = reflection.fingerprint([stage, instructions, data, schema])
        if budget is not None and (not math.isfinite(budget) or budget <= 0):
            raise ModelError("Model-call time budget exhausted.")
        cached = self._review_responses.get(key)
        if cached is not None and cached[2] != self.arm:
            reply, request_number, _ = cached
            self.reused_reviews.append({
                "arm": self.arm, "case_id": data["case"]["id"], "round": data["round"],
                "source_request_number": request_number,
            })
            return deepcopy(reply)
        reply = super().complete(stage, instructions, data, schema, budget=budget)
        self._review_responses[key] = (deepcopy(reply), len(self.calls), self.arm)
        return reply


def fixture_factory(*handlers):
    model = Model()

    class Stream(io.BytesIO):
        headers = {"Content-Type": "text/event-stream"}

    def open_fixture(request, *, timeout):
        payload = json.loads(request.data)
        data = json.loads(payload["messages"][-1]["content"])
        assert "expected_label" not in data
        if data["stage"] == "review":
            assert data["feedback"] == {"correct": None, "incorrect_labels": []}
            assert all("expected_label" not in entry for entry in data["prior_lessons"])
        result = model.complete(data["stage"], "", data, {}, budget=timeout)
        frames = [
            {"choices": [{"index": 0, "delta": {"content": json.dumps(result)}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        return Stream(b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
                      + b"data: [DONE]\n\n")
    return SimpleNamespace(open=open_fixture)


def run(work, manifest, dataset, lessons, model, plan, *, live, initial_results=None, learned_seed=None):
    if model.calls or model.reused_reviews:
        raise ValueError("Start each comparison with a fresh model client.")
    work.mkdir(parents=True)
    data = work / "heldout_input"
    data.mkdir()
    write(data / "benchmark.json", dataset)
    gateway = "personal_gateway" if live else "in_process_stub"
    seed_source = "synthetic_reference_fixture"
    if learned_seed is None:
        seed_path = work / "seed.sqlite3"
        scope = reflection.fingerprint([reflection.TASK, dataset["domain"], dataset["labels"], gateway])
        with closing(reflection.experience_store.open_store(seed_path)) as db, db:
            for entry in lessons:
                reflection.experience_store.save_lesson(db, scope, entry["case_id"], entry)
    else:
        seed_path, seed_report = learned_seed
        if (
            seed_report["source"] != gateway or seed_report["model_fingerprint"] != gateway_fingerprint(model)
            or seed_report["seed_sha256"] != digest(seed_path)
        ):
            raise ValueError("The learned seed was created with a different model setup or changed on disk.")
        seed_source = "model_extracted"
    seed_hash = digest(seed_path)
    result = {
        "source": gateway, "model": model.model, "model_profile": model.profile, "passed": False,
        "case_ids": [case["id"] for case in dataset["cases"]], "request_plan": plan,
        "seed_source": seed_source, "seed_sha256": seed_hash, "seed_database": str(seed_path),
        "calls": model.calls, "reused_initials": initial_results is not None,
        "review_response_policy": "reuse_identical_requests", "reused_reviews": model.reused_reviews,
    }
    setting = {"blind": True, "time_budget": manifest["time_budget_seconds"]}
    setting["personal_model" if live else "in_process_model"] = model
    offline_answer = (ROOT / "offline/answers.json").resolve()
    scoring = False
    auditing = True
    answer_reads = []

    def audit(event, args):
        if not auditing:
            return
        if not live and event.startswith("socket."):
            raise AssertionError(f"Unexpected network operation: {event}")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(args[0])).resolve() == offline_answer:
                if not scoring:
                    raise AssertionError("Held-out answers were opened before scoring.")
                answer_reads.append("score")

    sys.addaudithook(audit)
    try:
        if initial_results is None:
            try:
                reflection.run(data, work / "initial", None, review_rounds=0, **setting)
            finally:
                for call in model.calls:
                    call["arm"] = "initial"
            initial_results = work / "initial" / "norethink" / RESULT
        initial = score_benchmark.read_arm(initial_results, "norethink")
        initial_rows = score_benchmark.index_cases(initial, "initial")
        expected_ids = {case["id"] for case in dataset["cases"]}
        if initial_rows.keys() != expected_ids:
            raise ValueError("The initial results do not cover the selected cases.")
        frozen = reflection.fingerprint(initial)
        initial_hash = digest(initial_results)
        result.update(initial=str(initial_results), initial_sha256=initial_hash)
        arms = {}
        for arm, requires_request in ARMS:
            model.arm = arm
            start = len(model.calls)
            try:
                reflection.run(
                    data, work / arm, seed_path, review_rounds=manifest["review_rounds"],
                    initial_results=initial_results, guard_review=True,
                    require_request_feature=requires_request, **setting,
                )
            finally:
                for call in model.calls[start:]:
                    call["arm"] = arm
            reviewed = score_benchmark.read_arm(work / arm / "rethink" / RESULT, "rethink")
            if reviewed["initial_fingerprint"] != frozen:
                raise ValueError("The review arm did not reuse the shared frozen initial decisions.")
            rows = score_benchmark.index_cases(reviewed, "review", guarded=True)
            if rows.keys() != initial_rows.keys():
                raise ValueError("The review arm does not cover the frozen split.")
            for case_id, row in rows.items():
                draft = {field: initial_rows[case_id][field] for field in ("label", "reason")}
                if row["initial"] != draft:
                    raise ValueError("A review used a different initial decision.")
                score_benchmark.check_guard(
                    case_id, row, draft, row["retrieved_lessons"], reviewed["guard_context_policy"],
                    require_request_feature=requires_request,
                )
            arms[arm] = rows
        if digest(initial_results) != initial_hash or digest(seed_path) != seed_hash:
            raise ValueError("The frozen inputs changed during the comparison.")
        scoring = True
        references = frozen_file(manifest, "offline/answers.json")
        paired = {}
        totals = {arm: {"correct": 0, "improved": 0, "degraded": 0, "unchanged": 0} for arm in arms}
        for case_id, draft in initial_rows.items():
            expected = references[case_id]
            paired[case_id] = {"initial_label": draft["label"], "reference": expected}
            for arm, rows in arms.items():
                row = rows[case_id]
                correct = row["label"] == expected
                change = reflection.compare(draft["label"] == expected, correct)
                totals[arm]["correct"] += correct
                totals[arm][change] += 1
                paired[case_id][arm] = {
                    "final_label": row["label"], "stop_reason": row["stop_reason"], "outcome": change,
                    "logical_reviews": row["model_calls"],
                    "sent_seed_case_ids": [item["case_id"] for item in row["sent_lessons"]],
                }
        result.update(passed=True, cases=paired, metrics=totals)
    except (ValueError, ModelError, OSError) as error:
        result["error"] = str(error)
    finally:
        auditing = False
    result["answer_reads"] = answer_reads
    result["requests"] = len(model.calls)
    result["cost_by_arm"] = {}
    for arm in ("initial", *(name for name, _ in ARMS)):
        matching = [call for call in model.calls if call["arm"] == arm]
        result["cost_by_arm"][arm] = {
            "requests": len(matching),
            "reused_reviews": sum(item["arm"] == arm for item in model.reused_reviews),
            "observed_tokens": sum(call["usage"].get("total_tokens", 0) for call in matching),
        }
    result["calls_without_usage"] = sum("total_tokens" not in call["usage"] for call in model.calls)
    result["observed_tokens"] = sum(call["usage"].get("total_tokens", 0) for call in model.calls)
    write(work / "comparison.json", result)
    return result


def live_config():
    for variable, label in (("LLM_BASE_URL", "Base URL"), ("LLM_MODEL", "Model ID")):
        if not os.environ.get(variable, "").strip() and sys.stdin.isatty():
            os.environ[variable] = input(f"{label}: ").strip()
    if not os.environ.get("LLM_API_KEY", "").strip() and sys.stdin.isatty():
        with catch_warnings():
            simplefilter("error", GetPassWarning)
            key = getpass("API key (hidden): ").strip()
        if len(key) >= 2 and key[0] in ("'", '"') and key[0] == key[-1]:
            key = key[1:-1].strip()
        if any(not (33 <= ord(char) <= 126) or char in ("'", '"') for char in key):
            raise ValueError("Paste the complete API key without whitespace or control characters.")
        os.environ["LLM_API_KEY"] = key
    return ModelClient.from_env()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the personal gateway within the supplied total budget")
    mode.add_argument("--fixture", action="store_true", help="run against in-process streaming replies")
    parser.add_argument("--case-id", action="append", required=True, help="frozen held-out case ID, repeat as needed")
    parser.add_argument("--max-requests", type=int, help="hard lifetime budget for a live comparison")
    parser.add_argument("--out-dir", type=Path, help="new directory for a fixture or live comparison")
    parser.add_argument("--initial-results", type=Path, help="reuse matching frozen initials from this runner")
    parser.add_argument("--seed-dir", type=Path, help="use a read-only seed produced by learn_seed.py")
    args = parser.parse_args()
    try:
        manifest = scene_io.read_json(ROOT / "manifest.json")
        dataset, lessons = prepare(manifest, args.case_id)
        learned_seed = None
        if args.seed_dir is not None:
            source = "personal_gateway" if args.live else "in_process_stub" if args.fixture else None
            lessons, learned_seed = load_learned_seed(args.seed_dir.resolve(), dataset, lessons, source=source)
        plan = request_bound(dataset, lessons, manifest["review_rounds"], reuse_initial=args.initial_results is not None)
        if not (args.live or args.fixture):
            print(json.dumps({"mode": "request_plan", "case_ids": args.case_id, **plan}, indent=2))
            return 0
        if args.out_dir is None:
            parser.error("--out-dir is required for a comparison.")
        out = args.out_dir.resolve()
        if out.exists() or out.is_relative_to(ROOT):
            parser.error("Choose a new run directory outside the frozen data package.")
        if os.name == "nt" and out.drive.lower().startswith(("\\\\wsl.localhost", "\\\\wsl$")):
            parser.error("Choose a Windows-local output directory for the SQLite seed.")
        if args.live and (args.max_requests is None or args.max_requests < plan["max_requests"]):
            parser.error(f"Choose a run budget of at least {plan['max_requests']} requests for the selected comparison.")
        cap = min(args.max_requests, plan["max_requests"]) if args.max_requests is not None else plan["max_requests"]
        if args.live:
            config = live_config()
            opener = None
        else:
            config = ModelClient("https://offline.invalid/v1/chat/completions", "request-policy-fixture", "fixture")
            opener = fixture_factory
        model = PairedStreamClient(config, max_requests=cap, initial_cap=INITIAL_CAP, review_cap=REVIEW_CAP,
                                     opener_factory=opener)
        report = run(out, manifest, dataset, lessons, model, plan, live=args.live,
                     initial_results=args.initial_results.resolve() if args.initial_results else None,
                     learned_seed=learned_seed)
        print(json.dumps({"result": str(out / "comparison.json"), "passed": report["passed"],
                          "requests": report["requests"], "observed_tokens": report["observed_tokens"],
                          "reused_reviews": len(report["reused_reviews"]),
                          "metrics": report.get("metrics"), "error": report.get("error")}, ensure_ascii=True))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, ModelError, KeyError, sqlite3.Error, GetPassWarning) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
