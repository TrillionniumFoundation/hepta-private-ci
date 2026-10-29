"""Independent integration and augmented-state time propagation checks."""

import unittest

import numpy as np
from scipy.integrate import quad
from scipy.stats import norm

from experiments.first_passage_operator.operators import (
    RegenerativeSpec, apply_value, killed_laplace, operator_features,
)


class OperatorTests(unittest.TestCase):
    def test_spatial_transform_against_gaussian_integral(self):
        for mu in (-0.6, 0.3):
            for x in (0.04, 0.7):
                for z in (0.0, 0.4, 2.0):
                    sigma, t = 0.5, 0.4
                    scale = sigma * np.sqrt(t)
                    reference = quad(lambda y: np.exp(-z*y) * (
                        norm.pdf(y, x+mu*t, scale)
                        - np.exp(-2*mu*x/sigma**2)*norm.pdf(y, -x+mu*t, scale)),
                        0, np.inf, epsabs=2e-12)[0]
                    self.assertAlmostEqual(float(killed_laplace(x, mu, sigma, t, z)), reference, places=10)

    def test_boundary_start_has_an_immediate_atom(self):
        spec = RegenerativeSpec(-0.5, 0.4, 0.8, 0.2, 0.4)
        initial = operator_features(spec, 0.0, 0.0)
        self.assertEqual(initial["expected_events"], 1.0)
        self.assertEqual(initial["refractory_mass"], 1.0)
        later = operator_features(spec, 0.0, 0.7)
        reset = operator_features(spec, 0.8, 0.7, pending_refractory=0.2)
        np.testing.assert_array_equal(later["features"], reset["features"])
        self.assertEqual(later["discounted_events"], 1+reset["discounted_events"])
        self.assertEqual(later["discounted_active_time"], reset["discounted_active_time"])

    def test_mass_and_multiple_events(self):
        spec = RegenerativeSpec(-1.0, 0.4, 0.2, 0.08, 0.3)
        result = operator_features(spec, 0.08, 1.2)
        self.assertGreater(result["expected_events"], 3)
        self.assertAlmostEqual(result["features"][0] + result["features"][4], 1.0, places=12)
        self.assertLess(abs(result["mass_quadrature_defect"]), 2e-7)
        self.assertTrue(np.all(result["features"] >= 0))
        self.assertLess(result["discounted_active_time"], 1.2)

    def test_refractory_residual_time(self):
        spec = RegenerativeSpec(-0.5, 0.4, 0.8, 0.2, 0.7)
        held = operator_features(spec, 0.8, 0.06, pending_refractory=0.15)
        self.assertEqual(held["active_mass"], 0)
        np.testing.assert_allclose(held["features"][4:], np.exp(-np.array([0, 1, 3]) * 0.09))
        released = operator_features(spec, 0.8, 0.45, pending_refractory=0.15)
        direct = operator_features(spec, 0.8, 0.3)
        np.testing.assert_allclose(released["features"], direct["features"], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(released["discounted_features"],
                                   direct["discounted_features"]*np.exp(-0.7*0.15))
        self.assertAlmostEqual(released["discounted_active_time"],
                               direct["discounted_active_time"]*np.exp(-0.7*0.15))
        at_release = operator_features(spec, 0.8, 0.15, pending_refractory=0.15)
        self.assertEqual(at_release["active_mass"], 1.0)
        self.assertEqual(at_release["expected_events"], 0.0)

    def test_zero_discount_limit_and_linear_gradient(self):
        arguments = (-0.55, 0.32, 0.9, 0.06)
        zero = operator_features(RegenerativeSpec(*arguments, 0), 0.4, 1)
        small = operator_features(RegenerativeSpec(*arguments, 1e-6), 0.4, 1)
        self.assertAlmostEqual(zero["discounted_active_time"], small["discounted_active_time"], places=5)
        weights = np.linspace(-0.3, 0.8, 7)
        for index in range(7):
            delta = np.zeros(7)
            delta[index] = 1e-6
            gradient = (apply_value(zero, weights+delta) - apply_value(zero, weights-delta)) / 2e-6
            self.assertAlmostEqual(gradient, zero["discounted_features"][index], places=8)

    def test_high_decay_refractory_interval_retains_small_mass(self):
        from experiments.first_passage_operator.validate_operators import reference_features
        spec = RegenerativeSpec(-0.85, 0.48, 0.55, 0.04, 0.4)
        az, rz = (0.0, 1.0), (0.0, 25.0, 75.0)
        actual = operator_features(spec, 0.015, 0.75, active_decays=az, refractory_decays=rz)
        expected = reference_features(spec, 0.015, 0.75, az, rz)
        np.testing.assert_allclose(actual["features"], expected["features"], atol=1e-11, rtol=1e-10)

    def test_unrepresentable_occupation_tail_does_not_condition(self):
        spec = RegenerativeSpec(-0.3302758802149789, 0.2583716234743599,
                                1.1234724761073176, 0.10774084988507227, 0.0)
        item = operator_features(spec, 0.03967095989683911, 0.4309764713000755)
        self.assertTrue(np.isfinite(item["discounted_active_time"]))
        self.assertGreaterEqual(item["discounted_active_time"], 0)
        self.assertLessEqual(item["discounted_active_time"], 0.4309764713000755)
        self.assertLess(abs(item["mass_quadrature_defect"]), 1e-12)

    def test_invalid_refractory_state_is_not_survival(self):
        spec = RegenerativeSpec(-0.5, 0.4, 0.8, 0.2)
        with self.assertRaises(ValueError):
            operator_features(spec, 0.9, 0.1, pending_refractory=0.1)
        with self.assertRaises(ValueError):
            operator_features(spec, 0.8, 0.1, pending_refractory=0.3)


if __name__ == "__main__":
    unittest.main()
