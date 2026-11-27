"""Hand-counted metric and invalid-prediction regression tests."""

import unittest

import numpy as np

from cell_learning_metrics import calibrate_temperature, probabilities, task_metrics


class LearningMetricsTests(unittest.TestCase):
    def test_majority_predictions_do_not_hide_positive_failure(self):
        result = task_metrics(np.tile([0.8, 0.2], (4, 1)), [0, 0, 0, 1])
        self.assertEqual((result["forced_accuracy"], result["balanced_accuracy"],
                          result["positive_recall"]), (0.75, 0.5, 0.0))
        self.assertEqual(result["confusion_matrix"], [[3, 0], [1, 0]])

    def test_abstentions_remain_in_denominator(self):
        result = task_metrics([[0.9, 0.1], [0.4, 0.6], [0.8, 0.2]], [0, 1, 1])
        self.assertEqual((result["rows"], result["accepted"], result["abstained"]), (3, 2, 1))
        self.assertEqual(result["confusion_with_abstention_last_column"], [[1, 0, 0], [1, 0, 1]])
        self.assertAlmostEqual(result["overall_success"], 1 / 3)
        self.assertEqual(result["selective_accuracy"], 0.5)

    def test_no_eligible_rows_never_become_success(self):
        result = task_metrics([[1, 0], [0, 1]], [0, 1], eligible=[False, False])
        self.assertEqual((result["forced_accuracy"], result["overall_success"],
                          result["selective_accuracy"]), (1.0, 0.0, None))
        self.assertTrue(all(row["accepted"] == 0 for row in result["risk_coverage"]))

    def test_uniform_probabilistic_scores(self):
        result = task_metrics(np.full((2, 2), 0.5), [0, 1])
        self.assertAlmostEqual(result["nll"], np.log(2))
        self.assertAlmostEqual(result["brier_multiclass_sum"], 0.5)
        self.assertEqual(result["ece10_equal_width"], 0)

    def test_metric_inputs_reject_forgeries(self):
        for p, y in [([[0.5, 0.5]], [True]), ([[2, -1]], [0]),
                     ([[0.2, 0.2]], [0]), ([[np.nan, 0]], [0]), ([[1, 0]], [2])]:
            with self.subTest(p=p, y=y), self.assertRaises(ValueError):
                task_metrics(p, y)
        with self.assertRaises(ValueError):
            task_metrics([[1, 0]], [0], eligible=[1])

    def test_calibration_is_deterministic_and_can_reduce_overconfidence(self):
        logits = np.array([[8, -8], [8, -8], [-8, 8]], dtype=float)
        labels = np.array([0, 1, 1])
        temperature, report = calibrate_temperature(logits, labels)
        self.assertEqual(temperature, 8)
        self.assertTrue(report["boundary_selected"])
        self.assertLess(report["nll"], task_metrics(probabilities(logits), labels)["nll"])


if __name__ == "__main__":
    unittest.main()
