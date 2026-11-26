#!/usr/bin/env bash
# Check the container interface with official inputs; fixed fixture output is not a scored algorithm run.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
input_dir="${1:-$repo_root/data/selftest}"
if [[ ! -d "$input_dir" ]]; then
  echo "Input directory not found: $input_dir" >&2
  exit 2
fi
input_dir="$(cd "$input_dir" && pwd)"
docker_path() {
  case "$(uname -s)" in
    MINGW*|MSYS*) cygpath -w "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available" >&2
  exit 127
fi

run_dir="$(mktemp -d "${TMPDIR:-/tmp}/b05-ug3-smoke.XXXXXXXX")" || exit 1
mkdir -p "$run_dir/output"
input_mount="$(docker_path "$input_dir")"
output_mount="$(docker_path "$run_dir/output")"
build_context="$(docker_path "$repo_root/dev")"
case "$(uname -s)" in
  MINGW*|MSYS*) export MSYS_NO_PATHCONV=1 ;;
esac
image="b05-ug3-smoke:$(date +%Y%m%d%H%M%S)-$$"
printf 'Run directory: %s\n' "$run_dir"
printf 'Image tag: %s\n' "$image" > "$run_dir/commands.txt"
printf '%q ' docker build -t "$image" "$build_context" >> "$run_dir/commands.txt"
printf '\n' >> "$run_dir/commands.txt"
docker build -t "$image" "$build_context" > "$run_dir/build.log" 2>&1
build_rc=$?
printf 'build=%s\n' "$build_rc" > "$run_dir/exit_codes.txt"
if (( build_rc != 0 )); then
  echo "Build failed; see $run_dir/build.log" >&2
  exit "$build_rc"
fi
docker image inspect --format '{{.Id}}' "$image" > "$run_dir/image_id.txt"

for mode in validate-only fixture; do
  args=(--task all --test)
  if [[ "$mode" == fixture ]]; then
    args+=(--fixture --out-dir /output)
  else
    args+=(--validate-only)
  fi
  printf '%q ' docker run --rm --network none \
    --mount "type=bind,src=$input_mount,dst=/input,readonly" \
    --mount "type=bind,src=$output_mount,dst=/output" \
    "$image" "${args[@]}" >> "$run_dir/commands.txt"
  printf '\n' >> "$run_dir/commands.txt"
  docker run --rm --network none \
    --mount "type=bind,src=$input_mount,dst=/input,readonly" \
    --mount "type=bind,src=$output_mount,dst=/output" \
    "$image" "${args[@]}" > "$run_dir/$mode.log" 2>&1
  rc=$?
  printf '%s=%s\n' "$mode" "$rc" >> "$run_dir/exit_codes.txt"
  if (( rc != 0 )); then
    echo "$mode failed; see $run_dir/$mode.log" >&2
    exit "$rc"
  fi
done

check_code='from pathlib import Path; import runpy, sys; check = runpy.run_path("tests/check_submission.py")["check_outputs"]; issues, count = check(Path("/input"), Path("/output")); print(f"Checked {count} output files"); print("\n".join(issues)); sys.exit(bool(issues))'
printf '%q ' docker run --rm --network none --entrypoint python3 \
  --mount "type=bind,src=$input_mount,dst=/input,readonly" \
  --mount "type=bind,src=$output_mount,dst=/output,readonly" \
  "$image" -c "$check_code" >> "$run_dir/commands.txt"
printf '\n' >> "$run_dir/commands.txt"
docker run --rm --network none --entrypoint python3 \
  --mount "type=bind,src=$input_mount,dst=/input,readonly" \
  --mount "type=bind,src=$output_mount,dst=/output,readonly" \
  "$image" -c "$check_code" > "$run_dir/output_check.log" 2>&1
check_rc=$?
printf 'output_check=%s\n' "$check_rc" >> "$run_dir/exit_codes.txt"
find "$run_dir/output" -type f -print | sort > "$run_dir/output_files.txt"
if (( check_rc != 0 )); then
  echo "Output check failed; see $run_dir/output_check.log" >&2
  exit "$check_rc"
fi
printf 'Completed; records: %s\n' "$run_dir"
