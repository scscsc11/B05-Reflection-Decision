"""Build a knowledge seed from labeled synthetic civilian campus tickets."""

import argparse
import io
import json
import os
import sqlite3
from getpass import GetPassWarning
from pathlib import Path
from types import SimpleNamespace

from compare_personal import INITIAL_CAP, REVIEW_CAP, frozen_file, gateway_fingerprint, live_config
from run_comparison import ROOT, Model, digest, reflection, scene_io, write
from personal_stream import PersonalStreamClient
from src.llm_client import ModelClient, ModelError


def selected_inputs(manifest, ids):
    benchmark = frozen_file(manifest, "seed_input/benchmark.json")
    answers = frozen_file(manifest, "seed_input/answers.json")
    cases = {case["id"]: case for case in benchmark["cases"]}
    if len(set(ids)) != len(ids) or any(case_id not in cases for case_id in ids):
        raise ValueError("Choose distinct case IDs from the frozen seed inputs.")
    if cases.keys() != answers.keys() or any(label not in benchmark["labels"] for label in answers.values()):
        raise ValueError("The frozen seed references do not match their benchmark.")
    return benchmark | {"cases": [cases[case_id] for case_id in ids]}, {case_id: answers[case_id] for case_id in ids}


def fixture_opener(answers, *handlers):
    model = Model(seed_labels=answers)

    class Stream(io.BytesIO):
        headers = {"Content-Type": "text/event-stream"}

    def open_fixture(request, *, timeout):
        payload = json.loads(request.data)
        data = json.loads(payload["messages"][-1]["content"])
        if "expected_label" in data:
            raise AssertionError("A seed request contained the reference label.")
        result = model.complete(data["stage"], "", data, {}, budget=timeout)
        frames = [
            {"choices": [{"index": 0, "delta": {"content": json.dumps(result)}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        encoded = b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
        return Stream(encoded + b"data: [DONE]\n\n")

    return SimpleNamespace(open=open_fixture)


def build(work, manifest, dataset, answers, model, *, live):
    work.mkdir(parents=True)
    data = work / "seed_input"
    data.mkdir()
    write(data / "benchmark.json", dataset)
    write(data / "answers.json", answers)
    seed_path = work / "seed.sqlite3"
    source = "personal_gateway" if live else "in_process_stub"
    scope = reflection.fingerprint([reflection.TASK, dataset["domain"], dataset["labels"], source])
    counts = dict.fromkeys(("verified", "unverified", "rejected"), 0)
    report = {
        "passed": False, "source": source, "model": model.model, "model_profile": model.profile,
        "model_fingerprint": gateway_fingerprint(model), "manifest_sha256": digest(ROOT / "manifest.json"),
        "scope": scope, "seed_case_ids": list(answers), "status_counts": counts, "calls": model.calls,
    }
    setting = {"personal_model" if live else "in_process_model": model}
    try:
        reflection.run(
            data, work / "training", seed_path, review_rounds=1, use_history=False, blind=False,
            time_budget=manifest["time_budget_seconds"], checkpoint=work / "checkpoint.json", **setting,
        )
        entries = reflection.blind_seed(seed_path, scope, set())
        if {entry["case_id"] for entry in entries} != answers.keys() or any(
            entry["source"] != source or entry["expected_label"] != answers[entry["case_id"]]
            or entry.get("provenance") is None
            for entry in entries
        ):
            raise ValueError("Saved lessons do not match the selected seed inputs and run source.")
        for entry in entries:
            counts[entry["status"]] += 1
        report.update(
            passed=True, seed_sha256=digest(seed_path),
            lessons=[
                {key: entry[key] for key in ("case_id", "revision", "case_label", "status", "provenance")}
                for entry in entries
            ],
        )
    except (OSError, ValueError, ModelError, sqlite3.Error) as error:
        report["error"] = str(error)
    report["requests"] = len(model.calls)
    report["calls_without_usage"] = sum("total_tokens" not in call["usage"] for call in model.calls)
    report["observed_tokens"] = sum(call["usage"].get("total_tokens", 0) for call in model.calls)
    write(work / "seed_run.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="use the personal gateway within the supplied total budget")
    mode.add_argument("--fixture", action="store_true", help="build a seed with in-process streaming replies")
    parser.add_argument("--case-id", action="append", required=True, help="frozen seed case ID, repeat as needed")
    parser.add_argument("--max-requests", type=int, help="hard lifetime budget for a live seed build")
    parser.add_argument("--out-dir", type=Path, help="new directory for a fixture or live seed build")
    args = parser.parse_args()
    try:
        manifest = scene_io.read_json(ROOT / "manifest.json")
        dataset, answers = selected_inputs(manifest, args.case_id)
        bound = 2 * len(answers)
        if not (args.live or args.fixture):
            print(json.dumps({
                "mode": "seed_request_plan", "seed_case_ids": list(answers),
                "max_requests": bound, "requested_output_token_cap": len(answers) * (INITIAL_CAP + REVIEW_CAP),
            }, indent=2))
            return 0
        if args.out_dir is None:
            parser.error("--out-dir is required for a seed build.")
        out = args.out_dir.resolve()
        if out.exists() or out.is_relative_to(ROOT):
            parser.error("Choose a new output directory outside the frozen data package.")
        if os.name == "nt" and out.drive.lower().startswith(("\\\\wsl.localhost", "\\\\wsl$")):
            parser.error("Choose a Windows-local output directory for the SQLite seed.")
        if args.live and (args.max_requests is None or args.max_requests < bound):
            parser.error(f"Choose a run budget of at least {bound} requests for these seed cases.")
        cap = min(args.max_requests, bound) if args.max_requests is not None else bound
        if args.live:
            config, opener = live_config(), None
        else:
            config = ModelClient("https://offline.invalid/v1/chat/completions", "request-policy-fixture", "fixture")
            def opener(*handlers):
                return fixture_opener(answers, *handlers)

        model = PersonalStreamClient(config, max_requests=cap, initial_cap=INITIAL_CAP, review_cap=REVIEW_CAP,
                                     opener_factory=opener)
        report = build(out, manifest, dataset, answers, model, live=args.live)
        print(json.dumps({
            "result": str(out / "seed_run.json"), "passed": report["passed"], "requests": report["requests"],
            "observed_tokens": report["observed_tokens"], "status_counts": report["status_counts"],
            "error": report.get("error"),
        }, ensure_ascii=True))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, ModelError, KeyError, sqlite3.Error, GetPassWarning) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
