"""Finite-environment integrity tests; fake predictors are not model evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import data, interaction
from .test_data import record

MANIFEST = {"unit_test_model": True}


def task(split="train"):
    item = record(1, split)
    item["task"]["input"] = data.canonical(
        {
            "instruction": 'Return {"total":integer}.',
            "operation": "sum_counts",
            "source_excerpt": {"counts": [1, 2]},
        }
    ).decode()
    item["task"]["verifier"]["parameters"] = {"expected": {"total": 3}}
    item["final_answer"] = '{"total":3}'
    return item


class FakePredictor:
    def __init__(self, outputs):
        self.model_digest = data.digest(MANIFEST)
        self.outputs, self.requests, self.closed = iter(outputs), [], False

    def predict(self, request):
        self.requests.append(copy.deepcopy(request))
        return {
            "answer": next(self.outputs),
            "loaded_model_digest": self.model_digest,
            "input_tokens": 20,
            "output_tokens": 8,
            "elapsed_seconds": 0.001,
        }

    def close(self):
        self.closed = True


class InteractionTests(unittest.TestCase):
    def test_evaluation_retries_own_state_without_gold_or_reference(self):
        item = task("selection")
        item["task"]["verifier"]["parameters"] = {
            "expected": {"secret": "not-in-prompt"}
        }
        item["final_answer"] = '{"secret":"not-in-prompt"}'
        predictor = FakePredictor(['{"wrong":1}', '{"secret":"not-in-prompt"}'])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor", return_value=predictor),
            patch.object(
                interaction,
                "oracle_answer",
                side_effect=AssertionError("B/C oracle used"),
            ),
        ):
            root = Path(folder) / "evaluation"
            result = interaction.evaluate(MANIFEST, folder, [item], root)
            self.assertEqual(
                (
                    result["successes"],
                    result["cost"]["model_calls"],
                    result["cost"]["artifact_writes"],
                ),
                (1, 2, 2),
            )
            self.assertEqual(
                json.loads((root / "task-0/artifact-0.json").read_text()), {"wrong": 1}
            )
            self.assertNotIn("not-in-prompt", json.dumps(predictor.requests))
            self.assertNotIn("verifier", json.dumps(predictor.requests))
            self.assertIn('"semantic_ok":false', predictor.requests[1]["task"]["input"])
            self.assertTrue(predictor.closed)

    def test_invalid_json_is_not_applied_and_budget_is_enforced(self):
        predictor = FakePredictor(["not JSON", '{"total":0}', '{"total":3}'])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor", return_value=predictor),
        ):
            root = Path(folder) / "evaluation"
            result = interaction.evaluate(
                MANIFEST, folder, [task("confirmation")], root, max_steps=2
            )
            first = json.loads((root / "task-0/step-0.json").read_text())
            self.assertEqual(first["state_before"], first["state_after"])
            self.assertFalse((root / "task-0/artifact-0.json").exists())
            self.assertEqual(
                (result["successes"], result["cost"]["model_calls"]), (0, 2)
            )
            self.assertEqual(result["status"], "COMPLETE_DEVELOPMENT_EVALUATION")

    def test_collection_shadow_does_not_apply_and_correction_uses_visited_state(self):
        predictor = FakePredictor(['{"total":0}', '{"total":1}', '{"total":3}'])
        original = task()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor", return_value=predictor),
        ):
            root = Path(folder) / "collection"
            result = interaction.collect([original], MANIFEST, folder, root)
            shadow = json.loads((root / "shadow/task-0/step-0.json").read_text())
            self.assertEqual(shadow["state_before"], shadow["state_after"])
            self.assertFalse(shadow["applied"])
            controlled = data.load_records(root / "controlled.jsonl")
            self.assertIn('"total":1', controlled[0]["task"]["input"])
            self.assertIn('"semantic_ok":false', controlled[0]["task"]["input"])
            self.assertEqual(
                [r["family_id"] for r in controlled], [original["family_id"]] * 2
            )
            self.assertTrue(
                all(
                    r["teacher_id"] is None and r["exposure"] == "development"
                    for r in controlled
                )
            )
            self.assertEqual(
                result["records"], {"demonstration": 1, "shadow": 1, "controlled": 2}
            )
            self.assertEqual(
                [
                    s["train"]
                    for s in data.build_sft_examples(controlled, "trajectory")[0][
                        "segments"
                    ]
                ],
                [False, True, True],
            )
            self.assertFalse(result["actual_calls_equal"])

    def test_reference_collection_refuses_evaluation_split_before_model_load(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor") as loader,
        ):
            with self.assertRaisesRegex(ValueError, "A records only"):
                interaction.collect(
                    [task("selection")], MANIFEST, folder, Path(folder) / "blocked"
                )
            loader.assert_not_called()

    def test_inference_failure_is_incomplete_not_zero_score_and_retains_output(self):
        predictor = FakePredictor(['{"total":0}'])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor", return_value=predictor),
        ):
            root = Path(folder) / "failed"
            with self.assertRaises(StopIteration):
                interaction.evaluate(MANIFEST, folder, [task("selection")], root)
            self.assertEqual(
                json.loads((root / "FAILED.json").read_text())["status"], "INCOMPLETE"
            )
            self.assertTrue((root / "task-0/step-0.json").is_file())
            self.assertFalse((root / "RESULT.json").exists())
            self.assertTrue(predictor.closed)

    def test_model_json_fields_are_data_never_paths_or_commands(self):
        answer = '{"path":"../../outside","command":"touch outside"}'
        predictor = FakePredictor([answer])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(interaction, "load_predictor", return_value=predictor),
        ):
            root = Path(folder) / "bounded"
            result = interaction.evaluate(
                MANIFEST, folder, [task("selection")], root, max_steps=1
            )
            self.assertEqual((root / "task-0/artifact-0.json").read_text(), answer)
            self.assertEqual(result["successes"], 0)
            self.assertFalse((Path(folder) / "outside").exists())


if __name__ == "__main__":
    unittest.main()
