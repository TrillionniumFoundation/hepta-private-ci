"""Verify retries consume student observations and preserve the original task."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from . import data
from .repo_interaction_v2 import attempts, corrected_record, feedback
from .test_data import record
from .chat_protocol import native_examples, training_messages


class Predict:
    model_digest = "a" * 64

    def __init__(self, answers):
        self.answers, self.requests = iter(answers), []

    def predict(self, request):
        self.requests.append(copy.deepcopy(request))
        return {
            "answer": next(self.answers),
            "loaded_model_digest": self.model_digest,
            "input_tokens": 3,
            "output_tokens": 2,
            "hit_output_limit": False,
        }


class InteractionTests(unittest.TestCase):
    def test_retry_preserves_history_and_does_not_receive_gold(self):
        task = record(2)
        predictor = Predict(["", task["final_answer"]])
        with tempfile.TemporaryDirectory() as folder:
            result = attempts(predictor, task, Path(folder) / "attempt")
            self.assertTrue(result["success"])
            self.assertFalse(result["first_attempt_success"])
            second = predictor.requests[1]
            self.assertEqual(
                second["task"]["messages"][:2],
                [
                    {"role": "user", "content": task["task"]["input"]},
                    {"role": "assistant", "content": ""},
                ],
            )
            self.assertNotIn(
                task["final_answer"], second["task"]["messages"][2]["content"]
            )
            self.assertEqual(set(second["task"]), {"input", "messages"})
            derived = corrected_record(task, result, "controlled")
            self.assertEqual(derived["trajectory"][0]["content"], "")
            self.assertEqual(derived["lineage_id"], task["lineage_id"])
            messages, removed = training_messages(
                native_examples([derived], "trajectory")[0]
            )
            self.assertEqual(
                [m["content"] for m in messages if m["train"]], [task["final_answer"]]
            )
            self.assertEqual(removed, 1)

    def test_shadow_does_not_execute_verifier_or_claim_success(self):
        task = record(3)
        task["task"]["verifier"]["name"] = "not-registered"
        with tempfile.TemporaryDirectory() as folder:
            result = attempts(
                Predict(["candidate"]), task, Path(folder) / "shadow", execute=False
            )
        self.assertFalse(result["success"])
        self.assertIsNone(result["steps"][0]["verification"])

    def test_feedback_does_not_leak_oracle_or_worker_values(self):
        result = feedback(
            {
                "success": False,
                "result": {
                    "reason": "business_tests_failed",
                    "executed": True,
                    "controls_rejected": 1,
                    "result": {
                        "control_count": 2,
                        "observations": [{"secret_gold": "withheld"}],
                    },
                    "expected": "withheld",
                },
            }
        )
        self.assertNotIn("withheld", result)
        self.assertEqual(json.loads(result)["mutants_killed"], 1)
