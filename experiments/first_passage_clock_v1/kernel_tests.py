"""Behavioral regressions for probability/likelihood/clock contracts.

Run with: python -m unittest experiments.first_passage_clock_v1.kernel_tests
"""

import math
import unittest

import numpy as np

from . import kernels
from .oracle import (
    ReferenceParams, decimal_cdf_derivatives, decimal_discounted_derivatives,
    decimal_log_hit, decimal_log_survival, decimal_outcome_law, decimal_score_event, quadrature_outcome_law,
    shape_clock_negative_control,
)


class FirstPassageKernelTests(unittest.TestCase):
    def test_discounted_hit_preserves_discount_at_sigma_floor(self):
        value = math.exp(kernels.log_discounted_hit(.5, 1, 1, 1e-8, 1))
        # The neglected post-T first-passage tail is exp(-O(1e15)); the smooth
        # deterministic limit is exp(-rate*distance/mu), not one.
        self.assertAlmostEqual(value, math.exp(-.5), delta=2e-14)

    def test_sigma_derivative_at_deterministic_arrival(self):
        for sigma in (1e-4, 1e-6, 1e-8):
            with self.subTest(sigma=sigma):
                actual = kernels.cdf_derivatives(1, 1, 1, sigma)
                expected = decimal_cdf_derivatives(1, 1, 1, sigma)
                np.testing.assert_allclose(actual, expected, atol=2e-9, rtol=2e-8)

    def test_discount_tilt_retains_sub_ulp_drift_at_horizon(self):
        parameters = kernels.Params(1, 1e-8, 1)
        reference = ReferenceParams(1, 1e-8, 1)
        self.assertAlmostEqual(kernels.log_discounted_hit(1, 1, 1, 1e-8, 1),
                               decimal_log_hit(1, 1, 1, 1e-8, 1), delta=5e-10)
        np.testing.assert_allclose(kernels.discounted_hit_derivatives(1, 1, parameters),
                                   decimal_discounted_derivatives(1, 1, reference),
                                   atol=3e-9, rtol=2e-8)

    def test_survival_tail_is_not_rounded_cdf_complement(self):
        expected = decimal_log_survival(1, 1, 10, 1)
        actual = kernels.log_survival(1, 1, 10, 1)
        self.assertTrue(math.isfinite(actual))
        self.assertAlmostEqual(actual, expected, delta=2e-10)
        self.assertGreater(math.exp(actual), 0)
        self.assertAlmostEqual(kernels.log_survival(1, 1, 100, 1),
                               decimal_log_survival(1, 1, 100, 1), delta=2e-9)
        self.assertAlmostEqual(
            kernels.log_event_likelihood("no_hit", 1, 1, kernels.Params(100, 1, 0)),
            decimal_log_survival(1, 1, 100, 1), delta=2e-9,
        )

    def test_three_masses_match_independent_positive_integrals(self):
        parameters = kernels.Params(-.7, .5, .2)
        reference = ReferenceParams(-.7, .5, .2)
        actual = kernels.outcome_law(.25, 1.3, parameters)
        expected = quadrature_outcome_law(.25, 1.3, reference)
        np.testing.assert_allclose(actual, expected, atol=2e-9, rtol=2e-9)
        self.assertAlmostEqual(float(actual.sum()), 1, delta=2e-11)

    def test_tiny_cancellation_does_not_lose_temporal_boundary_layer(self):
        for distance, parameters in (
            (1, kernels.Params(1, 1e-4, 1e-12)),
            (1e-8, kernels.Params(50, 1, .3)),
        ):
            reference = ReferenceParams(parameters.mu, parameters.sigma, parameters.cancel_rate)
            actual = kernels.outcome_law(distance, 1, parameters)
            expected = decimal_outcome_law(distance, 1, reference)
            np.testing.assert_allclose(actual, expected, atol=0, rtol=2e-7)

    def test_no_hit_marginalizes_unobserved_cancellation(self):
        parameters = kernels.Params(.6, .8, .7)
        law = kernels.outcome_law(.7, 1.1, parameters)
        no_hit = math.exp(kernels.log_event_likelihood("no_hit", 1.1, .7, parameters))
        observed_survival = math.exp(kernels.log_event_likelihood("survive", 1.1, .7, parameters))
        self.assertAlmostEqual(no_hit, float(law[1] + law[2]), delta=2e-12)
        self.assertAlmostEqual(observed_survival, float(law[1]), delta=2e-12)
        self.assertGreater(no_hit, observed_survival)
        np.testing.assert_allclose(
            kernels.score_event("no_hit", 1.1, .7, parameters),
            decimal_score_event("no_hit", 1.1, .7, ReferenceParams(.6, .8, .7)),
            atol=2e-9, rtol=2e-8,
        )

    def test_zero_rate_double_root_has_finite_gradients(self):
        for rate in (0.0, 1e-24, 1e-12):
            parameters = kernels.Params(0.0, 1.0, rate)
            with self.subTest(rate=rate):
                expected = decimal_discounted_derivatives(1, 1, ReferenceParams(0, 1, rate))
                actual = kernels.discounted_hit_derivatives(1, 1, parameters)
                np.testing.assert_allclose(actual, expected, atol=3e-9, rtol=2e-8)
                self.assertTrue(np.isfinite(kernels.score_event("no_hit", 1, 1, parameters)).all())

    def test_initial_boundary_atom_and_zero_horizon(self):
        parameters = kernels.Params(.5, .8, .3)
        np.testing.assert_array_equal(kernels.outcome_law(0, 0, parameters), [1, 0, 0])
        np.testing.assert_array_equal(kernels.outcome_law(0, 1, parameters), [1, 0, 0])
        np.testing.assert_array_equal(kernels.outcome_law(1, 0, parameters), [0, 1, 0])
        self.assertEqual(kernels.log_event_likelihood("hit", 0, 0, parameters), 0)
        np.testing.assert_array_equal(kernels.score_event("hit", 0, 0, parameters), np.zeros(3))
        for event in ("cancel", "survive", "no_hit"):
            self.assertEqual(kernels.log_event_likelihood(event, 0, 0, parameters), -math.inf)
            with self.assertRaises(ValueError):
                kernels.score_event(event, 0, 0, parameters)
        self.assertEqual(kernels.log_fpt_cdf(1, 0, .5, .8), -math.inf)
        self.assertEqual(kernels.log_survival(1, 0, .5, .8), 0)

    def test_zero_cancellation_keeps_impossible_event_explicit(self):
        parameters = kernels.Params(.5, .8, 0)
        self.assertEqual(kernels.log_event_likelihood("cancel", .7, 1, parameters), -math.inf)
        with self.assertRaises(ValueError):
            kernels.score_event("cancel", .7, 1, parameters)
        self.assertEqual(kernels.outcome_law(1, .7, parameters)[2], 0)
        np.testing.assert_allclose(
            kernels.score_event("survive", .7, 1, parameters),
            decimal_score_event("survive", .7, 1, ReferenceParams(.5, .8, 0)),
            atol=2e-9, rtol=2e-8,
        )

    def test_clock_is_absent_from_shape_and_present_in_observation(self):
        speed = 4
        base = kernels.Params(.8, 1.2, .4)
        fast = kernels.Params(3.2, 2.4, 1.6)
        before, after, residual = shape_clock_negative_control(.8, 1.2, .4, speed)
        np.testing.assert_allclose(before, after, atol=1e-14)
        np.testing.assert_allclose(residual, np.zeros(2), atol=1e-14)
        np.testing.assert_allclose(kernels.outcome_law(1, 1.3 / speed, fast),
                                   kernels.outcome_law(1, 1.3, base), atol=2e-12)
        self.assertGreater(np.linalg.norm(kernels.outcome_law(1, 1.3, fast)
                                         - kernels.outcome_law(1, 1.3, base)), .05)
        for event in ("hit", "cancel"):
            self.assertAlmostEqual(kernels.log_event_likelihood(event, .7 / speed, 1, fast),
                                   kernels.log_event_likelihood(event, .7, 1, base) + math.log(speed),
                                   delta=2e-12)

    def test_invalid_numerics_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    kernels.outcome_law(1, 1, kernels.Params(value, 1, 0))
                with self.assertRaises(ValueError):
                    kernels.log_fpt_cdf(1, value, 0, 1)
        for parameters in (kernels.Params(0, 0, 0), kernels.Params(0, -1, 0), kernels.Params(0, 1, -.1)):
            with self.assertRaises(ValueError):
                kernels.outcome_law(1, 1, parameters)
        with self.assertRaises(ValueError):
            kernels.log_survival(-1, 1, 0, 1)
        with self.assertRaises(ValueError):
            kernels.log_fpt_cdf(1, -1, 0, 1)


if __name__ == "__main__":
    unittest.main()
