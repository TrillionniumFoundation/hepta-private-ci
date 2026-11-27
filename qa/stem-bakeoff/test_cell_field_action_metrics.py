"""Behavioral checks for ranking ties, invalid candidates and path retention."""

import unittest

import numpy as np

from cell_field_action_metrics import path_retention, rank_scores


class ActionMetricsTests(unittest.TestCase):
    def test_reversal_reports_real_regret_and_order(self):
        result = rank_scores(["zero", "short", "long"], [3, 2, 1], [1, 3, 2], tie_tolerance=0)
        self.assertEqual(result["pair_counts"], {"concordant": 1, "discordant": 2,
            "predicted_only_tie": 0, "actual_only_tie": 0, "both_tied": 0})
        self.assertEqual(result["predicted_top"], "long")
        self.assertEqual(result["executed_candidate_oracle"], "zero")
        self.assertEqual(result["predicted_top_actual_regret"], 1)
        self.assertAlmostEqual(result["kendall_tau_b"], -1 / 3)

    def test_ties_are_reported_without_inventing_strict_agreement(self):
        result = rank_scores(["first", "second", "third"], [1, 1 + 1e-12, 1],
                             [2, 1, 2], tie_tolerance=1e-10)
        self.assertIsNone(result["strict_order_agreement"])
        self.assertIsNone(result["kendall_tau_b"])
        self.assertEqual(result["strict_pair_coverage"], 0)
        self.assertEqual(result["pair_counts"]["predicted_only_tie"], 2)
        self.assertEqual(result["pair_counts"]["both_tied"], 1)
        self.assertEqual(result["predicted_top"], "first")
        self.assertEqual(result["worst_predicted_tie_actual_regret"], 1)

    def test_duplicate_missing_and_nonfinite_candidates_rejected(self):
        for ids, predicted, actual in [(["a", "a"], [0, 1], [0, 1]),
                (["a", "b"], [0], [0, 1]), (["a", "b"], [0, 1], [0, np.nan])]:
            with self.subTest(ids=ids, predicted=predicted, actual=actual):
                with self.assertRaises(ValueError):
                    rank_scores(ids, predicted, actual, tie_tolerance=1e-10)

    def test_retention_averages_sources_before_time_maximum(self):
        losses = np.array([[1, 1], [1.4, 0.5], [0.5, 1.4]])
        result = path_retention(losses, [1, 1], tolerance=0)
        self.assertTrue(result["future_probe_style_feasible"])
        self.assertAlmostEqual(result["maximum_future_mean_nll_excess"], -0.05)
        self.assertEqual(result["future_violation_steps"], [])

    def test_inherited_violation_is_not_an_impossible_future_constraint(self):
        result = path_retention([[1.2, 1.2], [0.9, 1.0], [1.0, 1.02]], [1, 1], tolerance=0)
        self.assertAlmostEqual(result["initial_mean_nll_excess"], 0.2)
        self.assertEqual(result["future_violation_steps"], [2])
        self.assertFalse(result["future_probe_style_feasible"])


if __name__ == "__main__":
    unittest.main()
