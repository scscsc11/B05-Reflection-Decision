"""Read and validate B05 scenes, and publish complete result files."""

import hashlib
import json
import math
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCENE_NAME = re.compile(r"scene[12]_[0-4]_([1-9][0-9]*)_([1-9][0-9]*)\.json")
RESULT_DIRS = ("norethink", "rethink")


@dataclass(frozen=True)
class Scene:
    """A validated input. The processor should treat data as read-only."""

    name: str
    rows: int
    columns: int
    data: dict[str, object]


def reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def read_json(path, *, expected_sha256: str | None = None):
    """Read unambiguous UTF-8 JSON and optionally verify the bytes being parsed."""
    raw = path.read_bytes() if expected_sha256 is not None else None
    if raw is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"{path}: SHA-256 does not match the frozen input.")
    try:
        text = raw.decode("utf-8") if raw is not None else path.read_text(encoding="utf-8")
        return json.loads(text, parse_constant=reject_json_constant, object_pairs_hook=unique_object)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc


def check_vector(values, length, label):
    if not isinstance(values, list) or len(values) != length:
        raise ValueError(f"{label} must be an array of length {length}")
    for index, value in enumerate(values):
        if type(value) is int or (type(value) is float and math.isfinite(value)):
            continue
        raise ValueError(f"{label}[{index}] must be a finite number")


def load_scene(path: Path) -> Scene:
    match = SCENE_NAME.fullmatch(path.name)
    if not match:
        raise ValueError(f"{path}: expected scene<S>_<I>_<N>_<M>.json")
    data = read_json(path)
    try:
        n, m = map(int, match.groups())
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
        missing = {"P", "v"} - data.keys()
        if missing:
            raise ValueError(f"missing required fields: {', '.join(sorted(missing))}")
        if not isinstance(data["P"], list) or len(data["P"]) != n:
            raise ValueError(f"P must have {n} rows")
        for index, row in enumerate(data["P"]):
            check_vector(row, m, f"P[{index}]")
        check_vector(data["v"], m, "v")
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
    return Scene(name=path.name, rows=n, columns=m, data=data)


def load_scenes(data_root: Path) -> list[Scene]:
    paths = sorted(path for path in data_root.iterdir() if path.suffix == ".json" and path.is_file())
    if not paths:
        raise ValueError(f"{data_root}: no top-level JSON scene files found")
    return [load_scene(path) for path in paths]


def check_result(result, length):
    """Check the output structure without assigning meaning to indices."""
    if not isinstance(result, dict) or result.keys() != {"results"}:
        raise ValueError("result must be an object with only the 'results' field")
    values = result["results"]
    if not isinstance(values, list) or len(values) != length:
        raise ValueError(f"results must be an array of length {length}")
    if any(type(value) is not int for value in values):
        raise ValueError("results entries must be integers")


def check_output_dir(data_root: Path, out_dir: Path) -> None:
    if out_dir.resolve().is_relative_to(data_root.resolve()):
        raise ValueError("output directory must be outside DATA_ROOT")
    if out_dir.exists():
        if not out_dir.is_dir():
            raise NotADirectoryError(f"{out_dir}: output path is not a directory")
        if any(out_dir.iterdir()):
            raise ValueError(f"{out_dir}: output directory must be empty")


def write_results(
    data_root: Path, out_dir: Path, results: dict[tuple[str, str], dict[str, object]],
    *, commit: Callable[[], None] | None = None,
) -> None:
    """Publish results, rolling back this publication if the state commit fails."""
    check_output_dir(data_root, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise ValueError(f"{out_dir}: output directory must be empty")

    # Stage on the output filesystem, so renaming also works on bind mounts.
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".b05-") as staging:
        stage = Path(staging)
        for mode in RESULT_DIRS:
            (stage / mode).mkdir()
        for (mode, name), payload in results.items():
            with (stage / mode / name).open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, allow_nan=False, separators=(",", ":"))
                stream.write("\n")

        published = []
        try:
            for mode in RESULT_DIRS:
                published.append((stage / mode).rename(out_dir / mode))
            if commit is not None:
                commit()
        except Exception:
            for target in reversed(published):
                target.rename(stage / target.name)
            raise
