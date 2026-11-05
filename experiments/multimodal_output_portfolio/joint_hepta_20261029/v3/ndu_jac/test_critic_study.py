"""Tests of fixed-target fitting, intervention truth and zero-noise limitations."""

import unittest

import numpy as np

from .critic_study import (EPSILONS, ETA, exact_value_gradient, fit_log_moment,
                          oscillatory_actor_counterexample, outcomes, predict)


class CriticStudyTests(unittest.TestCase):
    def test_proper_loss_targets_log_mean_not_mean_log(self):
        y, p = np.array([1.0, 9.0]), np.zeros(2)
        proper = fit_log_moment(p, y, degree=0)
        wrong = fit_log_moment(p, y, degree=0, objective="log_sample")
        self.assertTrue(proper["success"])
        self.assertAlmostEqual(proper["coefficient"][0], np.log(5), places=12)
        self.assertAlmostEqual(wrong["coefficient"][0], np.log(3), places=12)
        self.assertGreater(abs(predict(proper, [0])[0][0] - predict(wrong, [0])[0][0]), 0.3)

    def test_direct_gradient_matches_actual_interventions_through_zero_noise(self):
        p = np.linspace(-0.95, 0.95, 41)
        for epsilon in EPSILONS:
            with self.subTest(epsilon=epsilon):
                _, gradient = exact_value_gradient(p, epsilon)
                delta = 1e-5
                high = exact_value_gradient(p + delta, epsilon)[0]
                low = exact_value_gradient(p - delta, epsilon)[0]
                self.assertLess(float(np.max(np.abs(gradient - (high - low) / (2 * delta)))), 1e-9)

    def test_polynomial_derivative_of_fitted_value(self):
        p = np.linspace(-1, 1, 100)
        fit = fit_log_moment(p, np.exp(0.3 + 0.2 * p + 0.4 * p * p), degree=2)
        self.assertTrue(fit["success"])
        value, gradient = predict(fit, p)
        self.assertLess(float(np.max(np.abs(value + (0.3 + 0.2 * p + 0.4 * p * p) / ETA))), 1e-7)
        self.assertLess(float(np.max(np.abs(gradient + (0.2 + 0.8 * p) / ETA))), 1e-7)

    def test_declared_bounded_return_and_zero_noise_law(self):
        for epsilon in EPSILONS:
            reward, gradient = outcomes(np.linspace(-1, 1, 501), epsilon)
            self.assertGreaterEqual(float(reward.min()), -3)
            self.assertLessEqual(float(reward.max()), 2)
            self.assertTrue(np.isfinite(gradient).all())
        reward, _ = outcomes([0.5], 0)
        np.testing.assert_array_equal(reward[:, :2], reward[:, 2:])

    def test_small_value_error_can_harm_actor_and_is_rejected(self):
        result = oscillatory_actor_counterexample()
        self.assertLess(result["true_gradient"], 0)
        self.assertGreater(result["critic_gradient"], 0)
        self.assertGreater(result["critic_predicted_gain"], 0)
        self.assertLess(result["independent_exact_gain"], 0)
        self.assertEqual(result["disposition"], "no-update")
        self.assertEqual(result["gradient_error_at_prefix"], 2.0)

    def test_fit_and_domain_validation_rejects_invalid_inputs(self):
        for p, epsilon in (([1.1], 0), ([0], -0.1), ([0], True), ([float("nan")], 0)):
            with self.subTest(p=p, epsilon=epsilon), self.assertRaises(ValueError):
                outcomes(p, epsilon)
        for p, y in (([0], [0]), ([0], [-1]), ([0], [float("nan")]), ([0, 1], [1])):
            with self.subTest(p=p, y=y), self.assertRaises(ValueError):
                fit_log_moment(p, y, degree=0)
        with self.assertRaises(ValueError):
            fit_log_moment([0, 0], [1, 2], degree=2)
        with self.assertRaises(ValueError):
            fit_log_moment([0], [1], degree=0, objective="unknown")


if __name__ == "__main__":
    unittest.main()
