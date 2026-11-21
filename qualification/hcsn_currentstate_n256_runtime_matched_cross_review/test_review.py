import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ReviewTests(unittest.TestCase):
    def test_exact_preserved_red(self):
        value = json.loads((HERE / "REVIEW.json").read_text())
        self.assertEqual(value["coordinate_comparisons"], 69728)
        self.assertEqual(value["strict_bitwise_mismatches"], 665)
        self.assertEqual(sum(value["localization"]["mismatches_by_path"].values()), 665)
        self.assertFalse(value["qualification"])
        self.assertFalse(value["all_closed"])

    def test_review_did_not_execute_candidate(self):
        value = json.loads((HERE / "REVIEW.json").read_text())
        self.assertEqual(value["numerical_calls_by_review"], 0)
        self.assertEqual(value["torch_calls_by_review"], 0)
        self.assertEqual(value["optimizer_steps_by_review"], 0)

    def test_runtime_confounder_only_is_closed(self):
        value = json.loads((HERE / "REVIEW.json").read_text())
        self.assertTrue(value["runtime_version_confounder_eliminated"])
        self.assertEqual(value["arithmetic_or_path_cause"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
