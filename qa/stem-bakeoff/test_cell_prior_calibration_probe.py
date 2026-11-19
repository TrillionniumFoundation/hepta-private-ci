"""Prior-shift and calibration-only fitting tests on explicit fixtures."""

import unittest

import numpy as np

from cell_prior_calibration_probe import corrected_probability, evaluate_arms, fit_prior_temperature


class PriorCalibrationTests(unittest.TestCase):
    def test_zero_head_with_prior_correction_recovers_smoothed_class_prior(self):
        labels = np.array([0] * 80 + [1] * 20)
        fitted = fit_prior_temperature(np.zeros((100, 2)), labels)
        self.assertEqual(fitted["calibration_counts"], [80, 20])
        np.testing.assert_allclose(fitted["laplace_prior"], [81 / 102, 21 / 102])
        self.assertEqual(fitted["selected_temperature"], 1)
        predicted = corrected_probability(np.zeros((5, 2)), 4, fitted["laplace_prior"])
        np.testing.assert_allclose(predicted, np.tile([81 / 102, 21 / 102], (5, 1)))

    def test_prior_shift_improves_nll_without_inventing_discrimination(self):
        labels = np.array([0] * 80 + [1] * 20)
        logits = np.zeros((100, 2))
        fitted = fit_prior_temperature(logits, labels)
        scores = evaluate_arms(logits, labels, 1, fitted)
        baseline, corrected = scores["original_temperature_only"], scores["prior_corrected_temperature"]
        self.assertLess(corrected["nll"], baseline["nll"])
        self.assertEqual(corrected["balanced_accuracy"], .5)
        self.assertAlmostEqual(scores["calibration_prior_only"]["nll"], corrected["nll"])
        self.assertEqual(corrected["coverage"], 1)

    def test_prior_offset_is_not_divided_by_temperature(self):
        p = corrected_probability([[0., 0.]], 8, [.8, .2])
        np.testing.assert_allclose(p, [[.8, .2]])
        q = corrected_probability([[1., -1.]], 2, [.8, .2])
        self.assertAlmostEqual(q[0, 0] / q[0, 1], np.exp(1) * 4)

    def test_evaluation_labels_cannot_change_fitted_calibration_or_logits(self):
        logits = np.array([[1., -1.], [-1., 1.], [2., -2.], [.2, -.2]])
        calibration_labels = np.array([0, 1, 0, 1])
        original = logits.copy()
        fitted = fit_prior_temperature(logits, calibration_labels)
        frozen = dict(fitted)
        evaluate_arms(logits, calibration_labels, 1, fitted)
        evaluate_arms(logits, 1 - calibration_labels, 1, fitted)
        self.assertEqual(fitted, frozen)
        self.assertEqual(fit_prior_temperature(logits, calibration_labels), fitted)
        np.testing.assert_array_equal(logits, original)

    def test_nonfinite_or_invalid_prior_labels_reject(self):
        for prior in ([1, 0], [.8, .8], [np.nan, .2], [1]):
            with self.assertRaises(ValueError):
                corrected_probability([[0., 1.]], 1, prior)
        with self.assertRaises(ValueError):
            fit_prior_temperature([[0., 1.]], [True])
        with self.assertRaises(ValueError):
            corrected_probability([[np.inf, 1.]], 1, [.5, .5])


if __name__ == "__main__":
    unittest.main()
