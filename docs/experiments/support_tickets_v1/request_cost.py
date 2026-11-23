"""Audit logged model-attempt costs for one civilian support-ticket run."""

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

RESULT = "benchmark_results.json"
START = "INFO Model call started "
FINISH = "INFO Model call finished "
IDENTITY = ("case_id", "stage", "round", "attempt")
EVENT = (*IDENTITY, "seconds", "ok")
PHASES = {
    "seed": ("rethink", None),
    "initial": ("norethink", "initial"),
    "without_history": ("rethink", "review_without_history"),
    "with_history": ("rethink", "review_with_history"),
    "guarded": ("rethink", "review_with_guard"),
}


def identity(event):
    case_id, stage, round_, attempt = (event[field] for field in IDENTITY)
    if (
        not isinstance(case_id, str) or not case_id
        or stage not in ("initial", "review") or type(round_) is not int or type(attempt) is not int
        or round_ < 0 or (stage == "initial") != (round_ == 0) or attempt < 1
    ):
        raise ValueError("invalid model-call identity")
    return case_id, stage, round_, attempt


def finished(event):
    seconds, ok = event["seconds"], event["ok"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0 or type(ok) is not bool:
        raise ValueError("invalid finish duration or success flag")
    return (*identity(event), float(seconds), ok)


def seconds_total(events):
    return math.fsum(event[-2] for event in events.elements())


def entries(counter, fields):
    return [dict(zip(fields, key, strict=True), count=count) for key, count in sorted(counter.items())]


def read_invocation(path, relative, issues):
    raw = path.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    last = next((line.strip() for line in reversed(lines) if line.strip()), "")
    exit_match = re.fullmatch(r"exit=(-?\d+)", last)
    exit_code = int(exit_match[1]) if exit_match else None
    if last.startswith("exit=") and exit_code is None:
        issues.append(f"{relative}: malformed exit marker")

    starts = Counter()
    pending = Counter()
    observed = Counter()
    matched = Counter()
    for number, line in enumerate(lines, start=1):
        if not line.startswith((START, FINISH)):
            continue
        try:
            if line.startswith(START):
                key = identity(json.loads(line[len(START):]))
                if starts[key]:
                    issues.append(f"{relative}:{number}: duplicate start within one invocation for {key!r}")
                starts[key] += 1
                pending[key] += 1
            else:
                event = finished(json.loads(line[len(FINISH):]))
                key = event[:len(IDENTITY)]
                observed[event] += 1
                if not pending[key]:
                    issues.append(f"{relative}:{number}: finish without a matching start for {key!r}")
                    continue
                pending[key] -= 1
                matched[event] += 1
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            issues.append(f"{relative}:{number}: invalid call event ({exc})")
    pending = +pending
    if exit_code == 0 and pending:
        issues.append(f"{relative}: successful invocation has unclosed starts")
    return {
        "path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
        "exit_code": exit_code, "exit_marker_present": exit_code is not None,
        "started": starts.total(), "finished": observed.total(),
        "failed": sum(count for event, count in observed.items() if not event[-1]),
        "unknown_duration_count": pending.total(), "observed_seconds": seconds_total(observed),
        "unclosed_starts": entries(pending, IDENTITY),
    }, observed, matched


def read_published(path):
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    rows = data["cases"]
    if not isinstance(rows, list):
        raise ValueError("cases must be a list")
    seen = set()
    events = Counter()
    for row in rows:
        case_id = row["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen or not isinstance(row["calls"], list):
            raise ValueError("invalid published case ID or calls")
        seen.add(case_id)
        for call in row["calls"]:
            if "case_id" in call and call["case_id"] != case_id:
                raise ValueError(f"published call case ID disagrees with its row: {case_id}")
            events[finished(call | {"case_id": case_id})] += 1
    return hashlib.sha256(raw).hexdigest(), events


def audit(run_dir):
    issues = []
    score_path = run_dir / "offline_score.json"
    score_source = {"path": score_path.name, "sha256": None}
    score_counts = {}
    try:
        raw_score = score_path.read_bytes()
        score_source["sha256"] = hashlib.sha256(raw_score).hexdigest()
        score_counts = json.loads(raw_score.decode("utf-8"))["counts"]
        if not isinstance(score_counts, dict):
            raise ValueError("counts must be an object")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        issues.append(f"{score_path.name}: {exc}")

    phases = {}
    for phase, (mode, score_arm) in PHASES.items():
        logs = sorted((run_dir / "invocation_logs" / phase).glob("*.log"))
        if not logs:
            issues.append(f"{phase}: no invocation logs")
        invocations, observed, matched = [], Counter(), Counter()
        for path in logs:
            relative = str(path.relative_to(run_dir))
            try:
                report, current, current_matched = read_invocation(path, relative, issues)
            except (OSError, ValueError) as exc:
                issues.append(f"{relative}: {exc}")
                continue
            invocations.append(report)
            observed.update(current)
            matched.update(current_matched)
        phase_report = {
            "invocations": invocations,
            "started": sum(log["started"] for log in invocations),
            "finished": observed.total(), "matched_finished": matched.total(),
            "failed": sum(count for event, count in observed.items() if not event[-1]),
            "unknown_duration_count": sum(log["unknown_duration_count"] for log in invocations),
            "observed_seconds": seconds_total(observed),
            "logs_without_exit_marker": [log["path"] for log in invocations if not log["exit_marker_present"]],
        }
        phases[phase] = phase_report
        result_path = run_dir / phase / mode / RESULT
        relative = str(result_path.relative_to(run_dir))
        try:
            digest, published = read_published(result_path)
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            issues.append(f"{relative}: {exc}")
            continue
        missing, extra = published - matched, matched - published
        if missing:
            issues.append(f"{phase}: {missing.total()} published events missing from matched log finishes")
        phase_report["published"] = {
            "path": relative, "sha256": digest, "model_calls": published.total(),
            "model_seconds": seconds_total(published),
            "missing_log_events": entries(missing, EVENT),
            "unpublished_finished_events": entries(extra, EVENT),
            "unpublished_finished_count": extra.total(),
            "unpublished_finished_seconds": seconds_total(extra),
        }
        if score_arm is None:
            continue
        try:
            expected = score_counts[score_arm]
            expected_calls, expected_seconds = expected["model_calls"], expected["model_seconds"]
            if type(expected_calls) is not int or expected_calls != published.total() or (
                type(expected_seconds) not in (int, float) or not math.isfinite(expected_seconds)
                or not math.isclose(expected_seconds, seconds_total(published), rel_tol=1e-12, abs_tol=1e-12)
            ):
                raise ValueError("published calls or duration differ from the offline score")
            phase_report["offline_score_arm"] = score_arm
        except (ValueError, TypeError, KeyError) as exc:
            issues.append(f"{phase}: {exc}")
    return {"offline_score": score_source, "phases": phases, "issues": issues, "verified": not issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        parser.error(f"Run directory does not exist: {run_dir}")
    report = audit(run_dir)
    output = args.output if args.output is not None else run_dir / "request_cost.json"
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except OSError as exc:
        parser.exit(1, f"{exc}\n")
    print(output)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
