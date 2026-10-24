import unittest

import numpy as np

from cell_calibration_v2 import (apply_calibrator_logits, calibration_partition,
    discrimination_metrics, fit_calibrator, group_weights, smoothed_prior, weighted_nll)
from cell_learning_metrics import probabilities


class CalibrationTests(unittest.TestCase):
    def test_constant_scores_recover_laplace_prior(self):
        y = np.array([0]*90 + [1]*10)
        fitted = fit_calibrator(np.full((100, 2), 9.0), y)
        self.assertTrue(fitted["converged"])
        self.assertTrue(fitted["scale_zero_no_evidence"])
        self.assertIsNone(fitted["temperature"])
        np.testing.assert_allclose(probabilities(apply_calibrator_logits(np.zeros((3, 2)), fitted)),
                                   np.tile([91/102, 11/102], (3, 1)))

    def test_bias_and_scale_correct_misspecified_scores(self):
        rng = np.random.default_rng(99)
        x = rng.normal(size=1600)
        y = (rng.random(len(x)) < 1/(1+np.exp(-(x-1.1)))).astype(int)
        z = np.column_stack((np.zeros(len(x)), 4*x+3))
        fit = fit_calibrator(z, y)
        self.assertTrue(fit["converged"])
        self.assertGreater(fit["alpha"], 0)
        self.assertLess(fit["weighted_nll"], weighted_nll(z, y)-0.1)
        self.assertLess(fit["penalized_objective_final"], fit["penalized_objective_initial"])

    def test_negative_evidence_collapses_without_flipping_labels(self):
        y = np.tile([0, 1], 30)
        z = np.column_stack((np.zeros(len(y)), 5*(1-2*y)))
        fit = fit_calibrator(z, y)
        self.assertEqual(fit["alpha"], 0)
        self.assertTrue(fit["converged"])
        self.assertEqual(fit["prior"], [0.5, 0.5])

    def test_group_weights_prevent_replication_changing_prior(self):
        rows = [{"group_id": "a"}]*8 + [{"group_id": "b"}]*2
        y = np.array([0]*8+[1]*2)
        self.assertEqual(float(group_weights(rows).sum()), 2.0)
        np.testing.assert_array_equal(smoothed_prior(y, group_weights(rows)), [.5, .5])

    def test_partition_keeps_group_and_text_connected_components(self):
        rows = [dict(source_id=str(i), group_id=g, text=t) for i, (g, t) in enumerate(
            [("a", "same"), ("b", " SAME "), ("b", "other"), ("c", "third"), ("d", "fourth")])]
        left, right = calibration_partition(rows)
        self.assertEqual(set(left)|set(right), set(range(len(rows))))
        self.assertFalse(set(left)&set(right))
        self.assertTrue({0, 1, 2}.issubset(set(left)) or {0, 1, 2}.issubset(set(right)))
        reverse = rows[::-1]
        a, b = calibration_partition(reverse)
        self.assertEqual({rows[i]["source_id"] for i in left}, {reverse[i]["source_id"] for i in a})
        self.assertEqual({rows[i]["source_id"] for i in right}, {reverse[i]["source_id"] for i in b})

    def test_rank_metric_ties_and_fixed_prior_rule(self):
        y = np.array([0, 0, 1, 1])
        p = np.array([[.8, .2], [.5, .5], [.5, .5], [.1, .9]])
        score = discrimination_metrics(p, y, [.5, .5])
        self.assertEqual(score["auroc"], .875)
        self.assertEqual(score["balanced_accuracy_at_prior_threshold"], .75)
        self.assertEqual(score["positive_recall_at_prior_threshold"], .5)

    def test_nonfinite_and_missing_partition_rejected(self):
        with self.assertRaises(ValueError):
            fit_calibrator(np.array([[0., np.nan]]), np.array([0]))
        with self.assertRaises(ValueError):
            calibration_partition([dict(source_id="s", group_id="g", text="one")])


if __name__ == "__main__":
    unittest.main()
