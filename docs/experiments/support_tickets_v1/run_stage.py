"""Run one stage of the frozen civilian support-ticket comparison."""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

PACK = Path(__file__).resolve().parent
DEV = PACK.parents[2] / "dev"
RESULT = "benchmark_results.json"


def verify_inputs(manifest, names):
    for name in names:
        digest = hashlib.sha256((PACK / name).read_bytes()).hexdigest()
        if digest != manifest["sha256"][name]:
            raise ValueError(f"Frozen input was modified: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("seed", "initial", "without_history", "with_history", "guarded", "score"))
    parser.add_argument("run_dir", type=Path, help="dedicated directory for outputs and checkpoints")
    parser.add_argument("--dry-run", action="store_true", help="print the stage command with no model calls")
    args = parser.parse_args()
    stage = args.stage
    work = args.run_dir.resolve()
    if any(work.is_relative_to(PACK / folder) for folder in ("seed_input", "heldout_input", "offline")):
        parser.error("Choose a run directory outside the frozen input directories.")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    initial = work / "initial" / "norethink" / RESULT
    env = os.environ.copy()
    if stage == "score":
        command = [
            sys.executable, "-B", "-m", "src.score_benchmark",
            "--initial", str(initial),
            "--without-history", str(work / "without_history" / "rethink" / RESULT),
            "--with-history", str(work / "with_history" / "rethink" / RESULT),
            "--guarded", str(work / "guarded" / "rethink" / RESULT),
            "--answers", str(PACK / "offline" / "answers.json"),
            "--answers-sha256", manifest["sha256"]["offline/answers.json"],
            "--output", str(work / "offline_score.json"),
        ]
    else:
        # Use the approved gateway environment for live stages.
        folder = "seed_input" if stage == "seed" else "heldout_input"
        inputs = [f"{folder}/benchmark.json"]
        if stage == "seed":
            inputs.append(f"{folder}/answers.json")
        verify_inputs(manifest, inputs)
        env["DATA_ROOT"] = str(PACK / folder)
        rounds = 0 if stage == "initial" else manifest["review_rounds"]
        command = [
            sys.executable, "-B", "-m", "src.main", "--task", manifest["task"], "--test",
            "--out-dir", str(work / stage), "--review-rounds", str(rounds),
            "--time-budget", str(manifest["time_budget_seconds"]),
            "--checkpoint", str(work / "checkpoints" / f"{stage}.json"),
        ]
        if stage != "seed":
            command.append("--blind")
        if stage not in ("seed", "initial"):
            command.extend(("--initial-results", str(initial)))
        if stage in ("seed", "with_history", "guarded"):
            command.extend(("--knowledge-db", str(work / "knowledge.sqlite3")))
        if stage in ("seed", "without_history"):
            command.append("--no-history")
        if stage == "guarded":
            command.append("--guard-review")
        print(f"DATA_ROOT={shlex.quote(env['DATA_ROOT'])}", flush=True)
    print(shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    if stage == "score":
        return subprocess.run(command, cwd=DEV, env=env, check=False).returncode
    logs = work / "invocation_logs" / stage
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="invocation-", suffix=".log", dir=logs, delete=False,
    ) as stream:
        path = Path(stream.name)
        stream.write(f"$ {shlex.join(command)}\n")
        stream.flush()
        print(f"Invocation log: {path}", flush=True)
        result = subprocess.run(command, cwd=DEV, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        stream.write(f"\nexit={result.returncode}\n")
    if result.returncode:
        with path.open(encoding="utf-8") as stream:
            print("".join(deque(stream, maxlen=10)), end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
