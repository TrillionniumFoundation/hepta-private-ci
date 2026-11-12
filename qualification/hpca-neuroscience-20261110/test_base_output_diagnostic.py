"""Observable result and frozen-input controls for the base-only diagnostic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import base_output_diagnostic as probe

ROOT = Path(__file__).parent


class BaseOutputTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / "BASE_OUTPUT_PLAN.json").read_text())

    def test_existing_frozen_population(self):
        tasks, reference = probe.verify_inputs(
            self.plan, ROOT / "HPCA_V2_OOD_PLAN.json", ROOT / "ACTUAL_OOD_FORWARD_RESULT.json")
        self.assertEqual({task["id"] for task in tasks}, set(reference))
        self.assertEqual(len(tasks), 24)

    def test_changed_task_bytes_rejected_before_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            path.write_bytes((ROOT / "HPCA_V2_OOD_PLAN.json").read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "changed frozen input"):
                probe.verify_inputs(self.plan, path, ROOT / "ACTUAL_OOD_FORWARD_RESULT.json")

    def test_changed_previous_scores_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.json"
            data = json.loads((ROOT / "ACTUAL_OOD_FORWARD_RESULT.json").read_text())
            data["runs"][0]["predictions"][0]["p_yes"] = 0.999
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "changed frozen input"):
                probe.verify_inputs(self.plan, ROOT / "HPCA_V2_OOD_PLAN.json", path)

    def test_output_prefix_and_length_contract(self):
        self.assertEqual(probe.validate_generated_tokens([1, 3], [1, 3, 2]), [2])
        self.assertEqual(probe.validate_generated_tokens([1], [1] + [4]*8), [4]*8)
        for output in ([1, 3], [1, 4, 2], [1, 3] + [4]*9):
            with self.subTest(output=output), self.assertRaises(ValueError):
                probe.validate_generated_tokens([1, 3], output)

    def test_invalid_outputs_stay_in_primary_denominator(self):
        rows = [{"id": str(i), "truth": "yes" if i % 2 else "no",
                 "parsed": None if i % 2 else "no", "two_choice_prediction": "no",
                 "prior_p_yes_absolute_drift": 0.0, "label_vocabulary_mass": 0.01,
                 "emitted_token_ids": [2]} for i in range(24)]
        result = probe.summarize(rows)
        self.assertEqual((result["n"], result["greedy_valid"],
                          result["greedy_correct_including_invalid"]), (24, 12, 12))
        self.assertEqual(result["unique_public_tasks"], 24)
        self.assertEqual(result["independently_held_future_tasks"], 0)
        with self.assertRaises(ValueError):
            probe.summarize(rows[:-1])
        duplicate = copy.deepcopy(rows)
        duplicate[-1]["id"] = duplicate[0]["id"]
        with self.assertRaises(ValueError):
            probe.summarize(duplicate)


if __name__ == "__main__":
    unittest.main()
