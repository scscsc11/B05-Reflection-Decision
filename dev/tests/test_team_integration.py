"""Verify blind inference, frozen inputs and offline scoring using campus-ticket fixtures."""

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src import main, reflection, scene_io, score_benchmark
from tests.test_reflection_live import CASE, LABELS, ScriptedModel

RESULT = "benchmark_results.json"


def write_json(path, data):
    with path.open("x", encoding="utf-8") as writer:
        json.dump(data, writer, indent=2)


def run_blind_trial(work: Path) -> dict[str, Path]:
    """Create a separated in-process fixture trial for tests or local reproduction."""
    work.mkdir()
    seed_input, heldout = work / "seed_input", work / "heldout_input"
    seed_input.mkdir()
    heldout.mkdir()
    shared = {"domain": "campus-support-r1-fixture", "labels": LABELS}
    cases = [
        CASE | {"id": "fix"},
        {"id": "break", "topic": "schedule", "text": "Which room is tomorrow's lab in?", "features": ["room"]},
        {"id": "stay", "topic": "account", "text": "The campus portal rejects my password.", "features": ["login"]},
    ]
    write_json(heldout / "benchmark.json", shared | {"cases": cases})
    seed_cases = [
        CASE | {"id": "seed-materials", "text": "Sign-in works but the digital reading is missing."},
        cases[2] | {"id": "seed-account", "text": "My student account is locked."},
    ]
    write_json(seed_input / "benchmark.json", shared | {"cases": seed_cases})
    write_json(seed_input / "answers.json", {"seed-materials": "B", "seed-account": "A"})

    seed = work / "knowledge.sqlite3"
    seed_output = work / "seed"
    initial_output = work / "initial"
    initial = initial_output / "norethink" / RESULT
    arms = {
        "without_history": (["B", "B", "A", "A", "B", "C"], False, False),
        "with_history": (["B", "B", "A", "A", "A"], True, False),
        "guarded": (["B", "B"], True, True),
    }
    model_requests = {}
    paths = {"initial": initial, "seed": seed_output / "rethink" / RESULT}
    with patch.object(reflection.ModelClient, "from_env", side_effect=AssertionError("Gateway contacted")):
        reflection.run(
            seed_input, seed_output, seed, in_process_model=ScriptedModel(["A", "B", "A", "C"]),
        )
        seed_bytes = seed.read_bytes()
        with patch.object(reflection, "load_answers", side_effect=AssertionError("Blind run read answers")):
            reflection.run(
                heldout, initial_output, None, blind=True, review_rounds=0,
                in_process_model=ScriptedModel(["A", "C", "A"]),
            )
            for arm, (replies, use_history, guard) in arms.items():
                model = ScriptedModel(replies)
                reflection.run(
                    heldout, work / arm, seed if use_history else None,
                    blind=True, initial_results=initial, review_rounds=2,
                    use_history=use_history, guard_review=guard, in_process_model=model,
                )
                paths[arm] = work / arm / "rethink" / RESULT
                model_requests[arm] = [data for _, data in model.requests]

    if seed.read_bytes() != seed_bytes:
        raise AssertionError("The blind runs modified the knowledge seed.")
    write_json(work / "review_requests.json", model_requests)

    # This file is produced only after the blind stages return.
    answers = work / "heldout_answers.json"
    write_json(answers, {"fix": "B", "break": "C", "stay": "A"})
    inputs = {key: paths[key] for key in ("initial", "without_history", "with_history", "guarded")}
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()}
    score_file = work / "offline_score.json"
    status = score_benchmark.main([
        "--initial", str(initial), "--without-history", str(inputs["without_history"]),
        "--with-history", str(inputs["with_history"]), "--guarded", str(inputs["guarded"]),
        "--answers", str(answers), "--output", str(score_file),
    ])
    if status != 0 or hashes != {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()}:
        raise AssertionError("Offline scoring failed or modified inference results.")
    write_json(work / "inference_sha256.json", hashes)
    return paths | {"answers": answers, "score": score_file}


class TeamIntegrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.work = Path(folder.name) / "trial"

    def test_offline_score_and_knowledge_provenance(self):
        paths = run_blind_trial(self.work)
        trial = {key: scene_io.read_json(path) for key, path in paths.items()}
        scored = trial["score"]
        self.assertEqual(scored["gateway"], "in_process_stub")
        self.assertEqual(scored["initial_fingerprint"], reflection.fingerprint(trial["initial"]))
        self.assertEqual(scored["counts"]["initial"]["accuracy"], 2 / 3)
        self.assertEqual(scored["counts"]["initial"]["model_calls"], 3)
        for arm, requests in (("without_history", 6), ("with_history", 5)):
            with self.subTest(arm=arm):
                counts = scored["counts"][f"review_{arm}"]
                self.assertEqual((counts["improved"], counts["degraded"], counts["unchanged"]), (1, 1, 1))
                self.assertEqual(counts["accuracy"], 2 / 3)
                self.assertEqual(counts["model_calls"], requests)
                self.assertAlmostEqual(counts["model_seconds"], sum(row["model_seconds"] for row in trial[arm]["cases"]))

        requests = scene_io.read_json(self.work / "review_requests.json")
        for arm in ("without_history", "with_history", "guarded"):
            self.assertEqual(trial[arm]["initial_fingerprint"], scored["initial_fingerprint"])
            for row in trial[arm]["cases"]:
                self.assertIsNone(row["expected_label"])
                self.assertIsNone(row["correct"])
                self.assertFalse(row["feedback_available"])
                self.assertTrue(all(attempt["correct"] is None for attempt in row["rounds"]))
                sent = [call["prior_lessons"] for call in requests[arm] if call["case"]["id"] == row["id"]]
                self.assertEqual(sent, [row["sent_lessons"]] * row["review_rounds"])
                self.assertTrue(all("provenance" not in lesson for lesson in row["sent_lessons"]))
                self.assertEqual(row["model_calls"], len(sent))

        fix, broken, tie = trial["without_history"]["cases"]
        self.assertEqual((fix["initial_label"], fix["final_label"], fix["selected_round"]), ("A", "B", 2))
        lesson = fix["knowledge"]
        self.assertEqual((lesson["initial_label"], lesson["case_label"], lesson["source_round"]), ("A", "B", 2))
        self.assertTrue(lesson["from_selected_round"])
        self.assertEqual((lesson["status"], lesson["action"]), ("unverified", "not_saved"))
        self.assertEqual(lesson["conditions"], CASE["features"])
        self.assertEqual(lesson["applies_when"], fix["rounds"][1]["knowledge"]["applies_when"])
        self.assertEqual(broken["final_label"], "A")
        self.assertEqual(tie["stop_reason"], "round_limit")
        self.assertIsNone(tie["knowledge"])
        self.assertEqual(len(tie["rounds"]), 2)
        self.assertEqual(trial["with_history"]["cases"][0]["knowledge_version"], {"seed-materials": 1})
        for row in trial["guarded"]["cases"][1:]:
            self.assertEqual((row["review_gate"]["action"], row["model_calls"]), ("skipped", 0))
        retained = trial["seed"]["cases"][1]
        self.assertEqual(retained["label"], "A")
        self.assertEqual(retained["knowledge"]["status"], "rejected")
        self.assertEqual(retained["knowledge"]["case_label"], "C")
        self.assertFalse(retained["knowledge"]["from_selected_round"])

        cold = trial["without_history"]
        shuffled = cold | {"cases": list(reversed(cold["cases"]))}
        rescored = score_benchmark.score(
            trial["initial"], shuffled, trial["with_history"], trial["answers"], guarded=trial["guarded"],
        )
        self.assertEqual(rescored, scored)
        contaminated = deepcopy(cold)
        contaminated["cases"][0]["rounds"][0]["correct"] = True
        with self.assertRaisesRegex(ValueError, "in-process score"):
            score_benchmark.score(trial["initial"], contaminated, trial["with_history"], trial["answers"])
        older = {key: value for key, value in cold.items() if key != "blind_review_policy"}
        with self.assertRaisesRegex(ValueError, "same blind review protocol"):
            score_benchmark.score(trial["initial"], older, trial["with_history"], trial["answers"])

    def test_offline_cli_reads_frozen_answers_after_all_arm_files(self):
        paths = run_blind_trial(self.work)
        output = self.work / "verified_score.json"
        base = [
            "--initial", str(paths["initial"]), "--without-history", str(paths["without_history"]),
            "--with-history", str(paths["with_history"]), "--answers", str(paths["answers"]),
            "--output", str(output),
        ]
        missing = self.work / "missing_guarded.json"
        with patch.object(scene_io, "read_json", wraps=scene_io.read_json) as reader, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as error:
                score_benchmark.main([*base, "--guarded", str(missing)])
        self.assertEqual(error.exception.code, 1)
        self.assertNotIn(paths["answers"], [call.args[0] for call in reader.call_args_list])
        self.assertFalse(output.exists())

        guarded = [*base, "--guarded", str(paths["guarded"]), "--answers-sha256"]
        with redirect_stderr(StringIO()) as stderr:
            with self.assertRaises(SystemExit) as error:
                score_benchmark.main([*guarded, "0" * 64])
        self.assertEqual(error.exception.code, 1)
        self.assertIn("SHA-256 does not match", stderr.getvalue())
        self.assertFalse(output.exists())

        digest = hashlib.sha256(paths["answers"].read_bytes()).hexdigest()
        self.assertEqual(score_benchmark.main([*guarded, digest]), 0)
        result = scene_io.read_json(output)
        self.assertEqual(result.pop("reference_sha256"), digest)
        self.assertEqual(result, scene_io.read_json(paths["score"]))

    def test_seed_resume_preserves_accepted_and_rejected_review_sources(self):
        run_blind_trial(self.work)
        inputs = self.work / "seed_input"
        output = self.work / "resumed_seed"
        db_path = self.work / "resumed_seed.sqlite3"
        checkpoint = self.work / "seed_checkpoint.json"
        options = {"review_rounds": 2, "use_history": False, "checkpoint": checkpoint}
        interrupted = ScriptedModel(["A", "B", reflection.ModelError("seed interruption")])
        with self.assertRaisesRegex(reflection.ModelError, "seed interruption"):
            reflection.run(inputs, output, db_path, in_process_model=interrupted, **options)
        self.assertFalse(output.exists())
        records = scene_io.read_json(checkpoint)["records"]
        self.assertEqual(len(records), 1)
        accepted = {"initial_label": "A", "source_round": 1, "selected_round": 1, "final_label": "B"}
        self.assertEqual(records[0]["review"]["knowledge"]["provenance"], accepted)

        resumed = ScriptedModel(["A", "C"])
        reflection.run(inputs, output, db_path, in_process_model=resumed, **options)
        self.assertEqual([data["case"]["id"] for _, data in resumed.requests], ["seed-account", "seed-account"])
        domain, labels, _ = reflection.load_benchmark(inputs / "benchmark.json")
        scope = reflection.fingerprint([reflection.TASK, domain, labels, "in_process_stub"])
        lessons = {row["case_id"]: row for row in reflection.blind_seed(db_path, scope, {"heldout"})}
        self.assertEqual(lessons["seed-materials"]["provenance"], accepted)
        rejected = lessons["seed-account"]
        self.assertEqual(rejected["provenance"],
                         {"initial_label": "A", "source_round": 1, "selected_round": 0, "final_label": "A"})
        self.assertEqual((rejected["case_label"], rejected["status"]), ("C", "rejected"))

    def test_request_feature_guard_uses_separate_checkpoint_and_score_policy(self):
        paths = run_blind_trial(self.work)
        inputs = self.work / "heldout_input"
        output = self.work / "request_guard"
        seed = self.work / "knowledge.sqlite3"
        checkpoint = self.work / "request_guard_checkpoint.json"
        model = ScriptedModel([])
        run_in_process = partial(reflection.run, in_process_model=model)
        with (
            patch.dict(os.environ, {"DATA_ROOT": str(inputs)}),
            patch.object(reflection, "run", wraps=run_in_process),
            patch.object(reflection, "load_answers", side_effect=AssertionError("Blind run read answers")),
        ):
            status = main.main([
                "--task", reflection.TASK, "--out-dir", str(output), "--blind",
                "--guard-review", "--guard-require-request-feature",
                "--initial-results", str(paths["initial"]), "--knowledge-db", str(seed),
                "--checkpoint", str(checkpoint),
            ])
        self.assertEqual(status, 0)
        self.assertEqual(model.requests, [])
        guarded = scene_io.read_json(output / "rethink" / RESULT)
        self.assertEqual(guarded["guard_match_policy"], reflection.GUARD_REQUEST_POLICY)
        self.assertTrue(all(row["stop_reason"] == "no_unique_request_feature" for row in guarded["cases"]))

        initial, cold, warm, answers = (
            scene_io.read_json(paths[name]) for name in ("initial", "without_history", "with_history", "answers")
        )
        score = score_benchmark.score(initial, cold, warm, answers, guarded=guarded)
        self.assertEqual(score["guard_match_policy"], reflection.GUARD_REQUEST_POLICY)

        falsely_tagged = scene_io.read_json(paths["guarded"]) | {"guard_match_policy": reflection.GUARD_REQUEST_POLICY}
        with self.assertRaisesRegex(ValueError, "exactly one request feature"):
            score_benchmark.score(initial, cold, warm, answers, guarded=falsely_tagged)
        with self.assertRaisesRegex(ValueError, "Checkpoint differs"):
            reflection.run(
                inputs, self.work / "legacy_guard", seed, blind=True, guard_review=True,
                initial_results=paths["initial"], checkpoint=checkpoint, in_process_model=model,
            )

    def test_personal_stream_profile_pins_frozen_initials(self):
        run_blind_trial(self.work)
        inputs = self.work / "heldout_input"
        first = ScriptedModel(["A", "C", "A"])
        profile = {"stream": True, "output_token_caps": {"initial": 96, "review": 160}, "max_requests": 9}
        first.profile = profile
        initial_out = self.work / "personal_initial"
        reflection.run(inputs, initial_out, None, blind=True, review_rounds=0, personal_model=first)
        initial_path = initial_out / "norethink" / RESULT
        initial = scene_io.read_json(initial_path)
        self.assertEqual(initial["gateway"], "personal_gateway")
        self.assertEqual(initial["model_profile"], profile)

        resumed = ScriptedModel(["A", "C", "A"])
        resumed.profile = profile | {"max_requests": 3}
        target = self.work / "personal_review"
        reflection.run(
            inputs, target, None, blind=True, use_history=False, review_rounds=2,
            initial_results=initial_path, personal_model=resumed,
        )
        result = scene_io.read_json(target / "rethink" / RESULT)
        self.assertEqual(result["initial_fingerprint"], reflection.fingerprint(initial))
        self.assertEqual(result["model_fingerprint"], initial["model_fingerprint"])
        self.assertEqual(result["summary"]["model_calls"], 3)

        different = ScriptedModel([])
        different.profile = profile | {"output_token_caps": {"initial": 96, "review": 128}}
        with self.assertRaisesRegex(ValueError, "same cases and gateway"):
            reflection.run(
                inputs, self.work / "different_profile", None, blind=True, use_history=False,
                initial_results=initial_path, personal_model=different,
            )
        self.assertEqual(different.requests, [])

    def test_resume_keeps_completed_blind_rounds(self):
        paths = run_blind_trial(self.work)
        inputs = self.work / "heldout_input"
        output = self.work / "resumed"
        options = {
            "blind": True, "use_history": False, "initial_results": paths["initial"], "review_rounds": 2,
            "checkpoint": self.work / "checkpoint.json",
        }
        interrupted = ScriptedModel(["B", "B", reflection.ModelError("scripted interruption")])
        with self.assertRaisesRegex(reflection.ModelError, "scripted interruption"):
            reflection.run(inputs, output, None, in_process_model=interrupted, **options)
        self.assertFalse(output.exists())

        resumed = ScriptedModel(["A", "A", "B", "C"])
        reflection.run(inputs, output, None, in_process_model=resumed, **options)
        self.assertEqual([data["case"]["id"] for _, data in resumed.requests], ["break", "break", "stay", "stay"])
        result = scene_io.read_json(output / "rethink" / RESULT)
        self.assertEqual(result["execution"]["resumed_cases"], 1)
        self.assertEqual(result["execution"]["model_calls_this_run"], 4)
        self.assertEqual(result["summary"]["model_calls"], 6)
        self.assertEqual(result["cases"][0]["selected_round"], 2)
        self.assertTrue(all(row["correct"] is None for row in result["cases"]))
