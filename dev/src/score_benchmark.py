"""Score matched support-ticket blind runs after inference has finished."""

import argparse
import json
from pathlib import Path

if __package__:
    from . import reflection, scene_io
else:
    import reflection
    import scene_io


def read_arm(path: Path, mode: str) -> dict:
    data = scene_io.read_json(path)
    if (
        not isinstance(data, dict) or data.get("task") != reflection.TASK
        or data.get("blind") is not True or data.get("mode") != mode
        or any(not data.get(field) for field in reflection.BLIND_IDENTITY)
        or not isinstance(data.get("labels"), list)
        or any(not isinstance(label, str) for label in data["labels"])
    ):
        raise ValueError(f"{path}: expected a blind {mode} benchmark run.")
    return data


def index_cases(run: dict, stage: str, *, guarded: bool = False) -> dict[str, dict]:
    rows = run.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Blind run has no cases.")
    cases = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid case record.")
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in cases:
            raise ValueError("Case IDs must be nonempty and unique.")
        if row.get("label") not in run["labels"]:
            raise ValueError(f"{case_id!r}: label outside the benchmark categories.")
        reflection.validate_blind_decision(row, case_id)
        if stage == "initial":
            reflection.required_text(row.get("reason"), f"{case_id!r} initial reason")
        gate = row.get("review_gate") if guarded else None
        if isinstance(gate, dict) and gate.get("action") == "skipped":
            if row.get("calls") != [] or row.get("rounds") != []:
                raise ValueError(f"{case_id!r}: a skipped review must have no model calls or rounds.")
        else:
            reflection.validate_blind_calls(row.get("calls"), stage, case_id)
        cases[case_id] = row
    return cases


def check_guard(
    case_id: str, row: dict, draft: dict, history: list[dict], context_policy: str | None = None,
) -> None:
    gate = row.get("review_gate")
    if not isinstance(gate, dict):
        raise ValueError(f"{case_id!r}: missing review guard decision.")
    action = gate.get("action")
    if action not in ("skipped", "kept_initial", "accepted"):
        raise ValueError(f"{case_id!r}: unknown review guard action.")
    if context_policy is not None:
        if context_policy != reflection.GUARD_CONTEXT_POLICY:
            raise ValueError("Unknown guarded review context policy.")
        evidence = gate.get("case_ids")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError(f"{case_id!r}: invalid guard case IDs.")
        if action != "skipped" and not isinstance(gate.get("supported_label"), str):
            raise ValueError(f"{case_id!r}: review has no supported label.")
        topic_evidence = reflection.guarded_prompt_lessons(history, gate)
        if row.get("sent_lessons") != topic_evidence:
            raise ValueError(f"{case_id!r}: sent history differs from the authorized guard evidence.")
        if action != "skipped" and (
            not evidence or set(evidence) != {item["case_id"] for item in topic_evidence}
        ):
            raise ValueError(f"{case_id!r}: review did not use the evidence that authorized it.")
    if action in ("skipped", "kept_initial"):
        if row["label"] == draft["label"] and row.get("selected_round") == 0:
            return
    if action == "accepted":
        evidence = gate.get("case_ids")
        matching = [
            lesson["case_id"] for lesson in history
            if lesson.get("status") == "verified" and lesson.get("case_label") == row["label"]
        ]
        if (
            row["label"] == gate.get("supported_label") and isinstance(evidence, list)
            and evidence and all(item in matching for item in evidence)
        ):
            return
    raise ValueError(f"{case_id!r}: review guard decision is inconsistent with the output.")


def score(
    initial: dict, without_history: dict, with_history: dict, answers: dict, *, guarded: dict | None = None,
) -> dict:
    if initial.get("review_round_limit") != 0:
        raise ValueError("The initial input must be from an initial-only run.")
    initial_cases = index_cases(initial, "initial")
    digest = reflection.fingerprint(initial)

    if not isinstance(answers, dict) or any(answers.get(case_id) not in initial["labels"] for case_id in initial_cases):
        raise ValueError("The reference file must provide an allowed label for every evaluation case.")
    if (
        without_history.get("review_round_limit") != with_history.get("review_round_limit")
        or without_history.get("time_budget_seconds") != with_history.get("time_budget_seconds")
        or type(with_history.get("review_round_limit")) is not int
        or with_history["review_round_limit"] < 1
    ):
        raise ValueError("Both review arms must share the same round limit and time budget.")
    protocol = with_history.get("blind_review_policy")
    if without_history.get("blind_review_policy") != protocol:
        raise ValueError("Both review arms must use the same blind review protocol.")

    arms = {"initial": initial_cases}
    comparisons = [
        ("review_without_history", without_history, False, False),
        ("review_with_history", with_history, True, False),
    ]
    if guarded is not None:
        if any(guarded.get(field) != with_history.get(field) for field in (
            "review_round_limit", "time_budget_seconds", "knowledge_seed_fingerprint", "knowledge_seed_cases",
            "retrieval_policy", "blind_review_policy",
        )):
            raise ValueError("Guarded review must use the same protocol, budget and seed as ordinary history review.")
        comparisons.append(("review_with_guard", guarded, True, True))

    for name, run, enabled, is_guarded in comparisons:
        policy = "verified_history_guard" if is_guarded else "direct"
        if run.get("review_policy", "direct") != policy:
            raise ValueError("Review arm has the wrong review policy.")
        if any(initial[field] != run[field] for field in reflection.BLIND_IDENTITY):
            raise ValueError("Blind runs differ in benchmark data or model settings.")
        if run.get("initial_fingerprint") != digest or run.get("history_enabled") is not enabled:
            raise ValueError("Review arms must reuse the same initial results and have opposite history settings.")
        reviewed = index_cases(run, "review", guarded=is_guarded)
        if reviewed.keys() != initial_cases.keys():
            raise ValueError("Review arms must cover the same case IDs.")
        seed = run.get("knowledge_seed_cases", [])
        if (
            not isinstance(seed, list) or any(not isinstance(item, str) for item in seed)
            or bool(seed) != enabled or set(seed) & initial_cases.keys()
            or (enabled and not run.get("knowledge_seed_fingerprint"))
        ):
            raise ValueError("Review runs must use a separate knowledge seed only in the enabled arm.")
        for case_id, row in reviewed.items():
            draft = {field: initial_cases[case_id][field] for field in ("label", "reason")}
            if row.get("initial") != draft:
                raise ValueError(f"{case_id!r}: review started from a different initial result.")
            history = row.get("retrieved_lessons")
            if not isinstance(history, list) or any(
                not isinstance(item, dict) or item.get("case_id") not in seed for item in history
            ):
                raise ValueError(f"{case_id!r}: review used knowledge outside the declared seed.")
            if is_guarded:
                check_guard(case_id, row, draft, history, run.get("guard_context_policy"))
        arms[name] = reviewed

    baseline = {case_id: row["label"] == answers[case_id] for case_id, row in initial_cases.items()}
    counts = {}
    cases = {case_id: {"reference": answers[case_id]} for case_id in baseline}
    for name, rows in arms.items():
        measures = {"correct": 0, "cases": len(rows), "model_calls": 0, "model_seconds": 0.0}
        if name != "initial":
            measures.update(improved=0, unchanged=0, degraded=0)
        for case_id in baseline:
            row = rows[case_id]
            correct = row["label"] == answers[case_id]
            measures["correct"] += correct
            measures["model_calls"] += len(row["calls"])
            measures["model_seconds"] += sum(call["seconds"] for call in row["calls"])
            detail = {"label": row["label"], "correct": correct}
            if name != "initial":
                comparison = reflection.compare(baseline[case_id], correct)
                measures[comparison] += 1
                detail["change_from_initial"] = comparison
                detail["retrieved_lessons"] = [item["case_id"] for item in row["retrieved_lessons"]]
                if "sent_lessons" in row:
                    detail["sent_lessons"] = [item["case_id"] for item in row["sent_lessons"]]
                if "review_gate" in row:
                    detail["review_gate"] = row["review_gate"]
            cases[case_id][name] = detail
        measures["accuracy"] = measures["correct"] / measures["cases"]
        counts[name] = measures
    result = {
        "task": reflection.TASK, "domain": initial["domain"],
        "gateway": initial["gateway"], "model": initial["model"],
        "blind": True, "benchmark_fingerprint": initial["benchmark_fingerprint"],
        "initial_fingerprint": digest, "counts": counts, "cases": cases,
    }
    if protocol is not None:
        result["blind_review_policy"] = protocol
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--without-history", type=Path, required=True)
    parser.add_argument("--with-history", type=Path, required=True)
    parser.add_argument("--guarded", type=Path, help="additional blind review with the verified-history guard")
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = score(
            read_arm(args.initial, "norethink"),
            read_arm(args.without_history, "rethink"),
            read_arm(args.with_history, "rethink"),
            scene_io.read_json(args.answers),
            guarded=read_arm(args.guarded, "rethink") if args.guarded is not None else None,
        )
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text, end="")
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
