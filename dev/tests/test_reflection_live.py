"""Exercise support-ticket reflection with a scripted, in-process model."""

import json
import unittest
from copy import deepcopy
from time import perf_counter
from unittest.mock import patch

from src import reflection

LABELS = {"A": "Account access", "B": "Course materials", "C": "Class schedule"}
CASE = {
    "id": "ticket", "topic": "materials", "text": "I can sign in, but the lecture PDF will not download.",
    "features": ["download-failure"],
}
DRAFT = {"label": "A", "reason": "Initial reason."}


class ScriptedModel:
    endpoint = "in-process://support-tickets"
    model = "b05-r1-scripted-replies"
    use_json_schema = False
    timeout = 30.0

    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, stage, instructions, data, schema, *, budget):
        self.requests.append((instructions, deepcopy(data)))
        label = next(self.replies)
        if isinstance(label, reflection.ModelError):
            raise label
        if stage == "initial":
            return {"label": label, "reason": "Initial reason."}
        return {
            "label": label, "review": f"Reason for review {data['round']}.",
            "knowledge": {
                "problem": "Classify the primary symptom.",
                "lesson": "Check whether login already works.",
                "applies_when": "The ticket describes a working login and a failed file download.",
            },
        }


class ReflectionTests(unittest.TestCase):
    def review(
        self, replies, *, limit=5, expected=None, deadline=None, history=(), guard=False,
        case=CASE, require_request_feature=False,
    ):
        model = ScriptedModel(replies)
        calls = []
        result = reflection.review_case(
            model, LABELS, case, DRAFT, expected, list(history), calls,
            perf_counter() + 30 if deadline is None else deadline, limit,
            guard_review=guard, require_request_feature=require_request_feature,
        )
        return result, calls, model.requests

    def test_blind_vote_and_stopping(self):
        scenarios = (
            (["B", "B"], 5, "B", 2, "converged", {"A": 1, "B": 2}),
            (["B", "C"], 2, "A", 0, "round_limit", {"A": 1, "B": 1, "C": 1}),
            (["B", "A"], 5, "A", 0, "cycle_detected", {"A": 2, "B": 1}),
            (["A"], 5, "A", 0, "converged", {"A": 2}),
            (["B", "C", "B"], 5, "B", 3, "cycle_detected", {"A": 1, "B": 2, "C": 1}),
        )
        for replies, limit, label, selected, stop, counts in scenarios:
            with self.subTest(replies=replies):
                result, calls, requests = self.review(replies, limit=limit)
                self.assertEqual((result["label"], result["selected_round"], result["stop_reason"]),
                                 (label, selected, stop))
                self.assertEqual(result["selection"]["label_counts"], counts)
                self.assertEqual(result["selection"]["reason"],
                                 "initial_on_tie" if stop == "round_limit" else "most_frequent")
                self.assertIsNone(result["expected_label"])
                self.assertIsNone(result["correct"])
                self.assertFalse(result["feedback_available"])
                self.assertEqual([row["label"] for row in result["rounds"]], replies)
                self.assertEqual([row["round"] for row in result["rounds"]], list(range(1, len(replies) + 1)))
                self.assertTrue(all(row["correct"] is None for row in result["rounds"]))
                self.assertEqual(len(calls), len(replies))

                previous = DRAFT
                for row, (instructions, data) in zip(result["rounds"], requests, strict=True):
                    self.assertEqual(instructions, reflection.BLIND_REVIEW)
                    self.assertEqual(data["preliminary"], DRAFT)
                    self.assertEqual(data["previous"], previous)
                    self.assertEqual(data["feedback"], {"correct": None, "incorrect_labels": []})
                    self.assertNotIn("expected_label", data)
                    previous = {"label": row["label"], "reason": row["review"]}

    def test_model_cost_records_retry_and_success(self):
        replies = [reflection.ModelError("retry once", retry_after=0), "B", "B"]
        with (
            patch.object(reflection, "perf_counter", side_effect=[10, 10.125, 10.25, 11, 11.5, 12, 12.75]),
            self.assertLogs(reflection.logger, level="INFO") as log,
        ):
            result, calls, _ = self.review(replies, deadline=100)
        starts = []
        finishes = []
        for entry in log.records:
            prefix, _, payload = entry.getMessage().partition(" {")
            if prefix == "Model call started":
                starts.append(json.loads("{" + payload))
            elif prefix == "Model call finished":
                finishes.append(json.loads("{" + payload))
        self.assertEqual(finishes, [{"case_id": CASE["id"], **call} for call in calls])
        self.assertEqual(starts, [
            {field: call[field] for field in ("case_id", "stage", "round", "attempt")} for call in finishes
        ])
        row = reflection.audit_case(result | {"calls": calls}, DRAFT["label"])
        self.assertEqual([(call["round"], call["attempt"], call["ok"]) for call in calls],
                         [(1, 1, False), (1, 2, True), (2, 1, True)])
        self.assertEqual([call["seconds"] for call in calls], [0.25, 0.5, 0.75])
        self.assertEqual((row["model_calls"], row["model_seconds"]), (3, 1.5))
        self.assertEqual((row["review_rounds"], row["stop_reason"]), (2, "converged"))

    def test_feedback_excludes_disproved_labels_and_selects_verified_result(self):
        result, _, requests = self.review(["B", "C"], expected="C")
        self.assertEqual((result["label"], result["selected_round"], result["stop_reason"]),
                         ("C", 2, "verified_result"))
        self.assertTrue(result["feedback_available"])
        self.assertEqual([row["correct"] for row in result["rounds"]], [False, True])
        self.assertEqual([data["feedback"] for _, data in requests], [
            {"correct": False, "incorrect_labels": ["A"]},
            {"correct": False, "incorrect_labels": ["A", "B"]},
        ])
        self.assertEqual(requests[1][1]["previous"], {"label": "B", "reason": "Reason for review 1."})
        self.assertTrue(all(instructions == reflection.REVIEW for instructions, _ in requests))
        self.assertTrue(all("expected_label" not in data for _, data in requests))

    def test_feedback_retains_a_verified_initial(self):
        result, calls, requests = self.review(["B"], expected="A")
        self.assertEqual((result["label"], result["selected_round"], result["stop_reason"]),
                         ("A", 0, "kept_verified_initial"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(requests[0][1]["feedback"]["correct"])
        self.assertFalse(result["rounds"][0]["correct"])

    def test_guard_applies_to_the_vote_and_sends_only_its_evidence(self):
        verified = {
            "case_id": "seed", "revision": 2, "topic": "materials", "conditions": CASE["features"],
            "status": "verified", "case_label": "B", "lesson": "Advice omitted from a guarded prompt.",
        }
        unverified = verified | {"case_id": "unverified", "status": "unverified"}
        for replies, final, action in ((["B", "B"], "B", "accepted"), (["C", "C"], "A", "kept_initial")):
            with self.subTest(replies=replies):
                result, calls, requests = self.review(replies, history=[verified, unverified], guard=True)
                self.assertEqual((result["label"], result["stop_reason"], result["review_gate"]["action"]),
                                 (final, "converged", action))
                self.assertEqual(result["selection"]["voted_label"], replies[0])
                self.assertEqual(len(calls), 2)
                sent = {key: value for key, value in verified.items() if key != "lesson"}
                self.assertEqual(result["sent_lessons"], [sent])
                self.assertTrue(all(data["prior_lessons"] == [sent] for _, data in requests))

    def test_request_feature_guard_skips_missing_or_ambiguous_request(self):
        for request_features in ([], ["request:"], ["request:download-material", "request:confirm-location"]):
            with self.subTest(request_features=request_features):
                features = [*CASE["features"], *request_features]
                case = CASE | {"features": features}
                verified = {
                    "case_id": "seed", "revision": 1, "topic": case["topic"], "conditions": features,
                    "status": "verified", "case_label": "B",
                }
                result, calls, requests = self.review(
                    [], case=case, history=[verified], guard=True, require_request_feature=True,
                )
                self.assertEqual((result["label"], result["selected_round"]), (DRAFT["label"], 0))
                self.assertEqual(result["review_gate"]["action"], "skipped")
                self.assertEqual(result["stop_reason"], "no_unique_request_feature")
                self.assertEqual((calls, requests, result["sent_lessons"]), ([], [], []))

    def test_request_feature_guard_requires_matching_verified_evidence(self):
        features = [*CASE["features"], "request:download-material"]
        case = CASE | {"features": features}
        verified = {
            "case_id": "seed", "revision": 1, "topic": case["topic"], "conditions": features,
            "status": "verified", "case_label": "B",
        }
        other_request = verified | {
            "case_id": "other", "conditions": [*CASE["features"], "request:confirm-location"],
            "case_label": "C",
        }
        unverified = verified | {"case_id": "unverified", "status": "unverified", "case_label": "C"}
        result, calls, requests = self.review(
            ["B", "B"], case=case, history=[verified, other_request, unverified],
            guard=True, require_request_feature=True,
        )
        self.assertEqual((result["label"], result["review_gate"]["action"]), ("B", "accepted"))
        self.assertEqual(result["sent_lessons"], [verified])
        self.assertEqual(len(calls), 2)
        self.assertEqual([data["prior_lessons"] for _, data in requests], [[verified], [verified]])

        same_request_conflict = verified | {"case_id": "conflict", "case_label": "C"}
        for history in ([other_request, unverified], [verified, same_request_conflict]):
            with self.subTest(history=history):
                result, calls, requests = self.review(
                    [], case=case, history=history, guard=True, require_request_feature=True,
                )
                self.assertEqual(result["label"], DRAFT["label"])
                self.assertEqual(result["review_gate"]["action"], "skipped")
                self.assertEqual(result["stop_reason"], "no_unique_verified_match")
                self.assertEqual((calls, requests, result["sent_lessons"]), ([], [], []))
