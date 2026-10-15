"""Source-only qualification denial against actual ten-family results."""
import copy
import json
import unittest
from pathlib import Path

from amcn_original_research_gate import assess


SOURCE = Path(__file__).with_name("ORIGINAL_TRAINED_RANK_HEADS_20261015.json")


class OriginalDenialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(SOURCE.read_text())

    def test_real_source_remains_no_go(self):
        result = assess(self.original)
        self.assertEqual(result["original_heldout_questions"], 400)
        self.assertEqual(result["typed_gain_over_bm25_proxy_only"], 10)
        self.assertEqual(result["typed_hit3"], 192)
        self.assertTrue(result["typed_vs_untyped_tie"])
        self.assertTrue(result["typed_vs_wrong_route_tie"])
        self.assertFalse(result["automatic_fission_fusion_eligible"])

    def test_missing_original_family_denied(self):
        data = copy.deepcopy(self.original)
        del data["per_split"]["retrospective_heldout_b"]
        with self.assertRaises(ValueError):
            assess(data)

    def test_counterfeit_heldout_outcome_denied(self):
        data = copy.deepcopy(self.original)
        data["per_split"]["retrospective_heldout_a"]["typed_equal_budget"]["hit3"] += 1
        with self.assertRaisesRegex(ValueError, "delta drift"):
            assess(data)

    def test_missing_candidate_denominator_denied(self):
        data = copy.deepcopy(self.original)
        data["per_split"]["retrospective_heldout_a"]["typed_equal_budget"]["questions"] -= 1
        with self.assertRaisesRegex(ValueError, "denominator"):
            assess(data)

    def test_fake_reader_success_denied(self):
        data = copy.deepcopy(self.original)
        data["real_reader_answers_this_trial"] = 400
        with self.assertRaises(ValueError):
            assess(data)

    def test_false_independent_future_denied(self):
        data = copy.deepcopy(self.original)
        data["independent_future_calendar_windows"] = 2
        with self.assertRaises(ValueError):
            assess(data)

    def test_automatic_admission_denied(self):
        data = copy.deepcopy(self.original)
        data["superiority_claim"] = True
        with self.assertRaises(ValueError):
            assess(data)


if __name__ == "__main__":
    unittest.main()
