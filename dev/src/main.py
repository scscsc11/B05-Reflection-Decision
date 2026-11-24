#!/usr/bin/env python3
"""B05 entry point for formal runs, validation, and test fixtures."""

import argparse
import logging
import os
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from time import perf_counter

if __package__:
    from . import reflection, scene_io
else:
    import reflection
    import scene_io

logger = logging.getLogger(__name__)

Processor = Callable[[scene_io.Scene, str], list[int]]


class ProcessingError(RuntimeError):
    """A processor failed, or its result did not match the output schema."""


def load_formal_processor() -> Processor | None:
    """Load process(scene, mode) from processor.py beside this entry point."""
    if not Path(__file__).with_name("processor.py").is_file():
        return None
    module_name = f"{__package__}.processor" if __package__ else "processor"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ProcessingError(f"Missing dependency for src/processor.py: {exc.name!r}.") from exc
    except Exception as exc:
        raise ProcessingError(f"Cannot load src/processor.py ({type(exc).__name__}): {exc}") from exc
    process = getattr(module, "process", None)
    if not callable(process):
        raise ProcessingError("src/processor.py must define a callable process(scene, mode).")
    return process


def fixture_result(scene: scene_io.Scene, _mode: str) -> list[int]:
    """Return a fixed payload for exercising the file interface."""
    return [1] * scene.rows


def run_batch(data_root: Path, out_dir: Path, processor: Processor | None) -> None:
    """Load the batch, then call the processor once per scene and output mode."""
    started = perf_counter()
    scenes = scene_io.load_scenes(data_root)
    logger.info("Validated %d scene files in %s (%.3fs).", len(scenes), data_root, perf_counter() - started)
    if processor is None:
        return

    started = perf_counter()
    results = {}
    for scene in scenes:
        for mode in scene_io.RESULT_DIRS:
            try:
                values = processor(scene, mode)
                scene_io.check_result({"results": values}, scene.rows)
            except Exception as exc:
                raise ProcessingError(f"{scene.name} [{mode}]: {exc}") from exc
            results[mode, scene.name] = {"results": values.copy()}
    logger.info("Prepared %d results (%.3fs).", len(results), perf_counter() - started)

    started = perf_counter()
    scene_io.write_results(data_root, out_dir, results)
    logger.info(
        "Wrote %d files to %s (%d each in norethink and rethink, %.3fs).",
        len(results), out_dir, len(scenes), perf_counter() - started,
    )


def main(argv=None, *, processor: Processor | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="all")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=os.environ.get("OUTPUT_DIR", "/output"))
    benchmark = parser.add_argument_group("support-tickets options")
    benchmark.add_argument("--knowledge-db", type=Path, help="SQLite path for the support-ticket benchmark")
    benchmark.add_argument("--review-rounds", type=int, default=2, help="maximum reviews per case (0 for initial only)")
    benchmark.add_argument("--no-history", action="store_true", help="skip retrieval for the history comparison")
    benchmark.add_argument("--time-budget", type=float, default=180.0, help="benchmark model-call budget in seconds")
    benchmark.add_argument("--simulated-gateway", action="store_true", help="mark test service outputs and isolate its knowledge")
    benchmark.add_argument("--checkpoint", type=Path, help="resume completed cases from this JSON file")
    benchmark.add_argument("--blind", action="store_true", help="run without reference answers or knowledge writes")
    benchmark.add_argument("--initial-results", type=Path, help="reuse the blind initial-only results in review")
    benchmark.add_argument("--guard-review", action="store_true", help="require matching verified history for blind changes")
    benchmark.add_argument(
        "--guard-require-request-feature", action="store_true",
        help="also require a single request: feature in the guarded match",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--fixture", dest="mode", action="store_const", const="fixture",
        help="write fixed, non-scoring test output",
    )
    modes.add_argument(
        "--validate-only", dest="mode", action="store_const", const="validate-only",
        help="validate the input batch without writing output",
    )
    parser.set_defaults(mode="formal")
    args = parser.parse_args(argv)

    started = perf_counter()
    status = 1
    logger.info("Run started: mode=%s task=%s test=%s.", args.mode, args.task, args.test)
    try:
        data_root = Path(os.environ.get("DATA_ROOT", "/input"))
        if args.guard_require_request_feature and not args.guard_review:
            raise ValueError("--guard-require-request-feature requires --guard-review.")
        if args.guard_review and args.task != reflection.TASK:
            raise ValueError("--guard-review is for the support-ticket benchmark.")
        if args.task == reflection.TASK:
            if args.mode != "formal":
                raise ValueError("--task support-tickets uses the model gateway. Omit --fixture and --validate-only.")
            reflection.run(
                data_root, args.out_dir, args.knowledge_db,
                review_rounds=args.review_rounds, use_history=not args.no_history,
                simulated=args.simulated_gateway, time_budget=args.time_budget,
                checkpoint=args.checkpoint, blind=args.blind, initial_results=args.initial_results,
                guard_review=args.guard_review, require_request_feature=args.guard_require_request_feature,
            )
            status = 0
            return status

        if args.mode == "formal":
            if processor is None:
                processor = load_formal_processor()
            if processor is None:
                status = 3
                logger.error("Formal processing is not implemented. Provide src/processor.py with process(scene, mode).")
                return status
        elif args.mode == "fixture":
            processor = fixture_result
            logger.info("Generating fixed test fixtures.")
        elif args.mode == "validate-only":
            processor = None
        run_batch(data_root, args.out_dir, processor)
        status = 0
    except (OSError, ValueError, ProcessingError, reflection.ModelError) as exc:
        logger.error("%s", exc)
    finally:
        logger.info("Run finished: mode=%s exit=%d total=%.3fs.", args.mode, status, perf_counter() - started)
    return status


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
