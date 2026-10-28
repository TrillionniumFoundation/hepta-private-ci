"""Independent integral, derivative, and moving-boundary checks."""

import math
import unittest

import numpy as np
from scipy.integrate import quad

from experiments.free_boundary_neuron.math.hitting import (
    fpt_density,
    hit_probability_and_gradient,
    hit_readout,
    hit_sensitivities,
)
from experiments.free_boundary_neuron.math.moving import (
    linear_boundary_readout,
    moving_boundary_reference,
)
from experiments.free_boundary_neuron.math.roots import stable_roots


class RootTests(unittest.TestCase):
    def test_roots_remain_resolved_under_large_drift_cancellation(self):
        for mu in (-1e8, -1.0, 0.0, 1.0, 1e8):
            with self.subTest(mu=mu):
                root = stable_roots(mu, 0.7, 0.3)
                self.assertGreater(root.kappa, 0)
                residual = 0.5 * 0.7**2 * root.kappa**2 + mu * root.kappa - 0.3
                scale = abs(0.5 * 0.7**2 * root.kappa**2) + abs(mu * root.kappa) + 0.3
                self.assertLess(abs(residual) / scale, 5e-16)
                self.assertAlmostEqual(
                    root.gamma_plus * root.kappa, 0.6 / 0.7**2, places=12
                )

    def test_root_derivatives_match_full_parameter_perturbations(self):
        for parameters in ((0.4, 0.8, 0.2), (-0.5, 1.1, 0.4), (0.0, 0.6, 0.1)):
            root = stable_roots(*parameters)
            for index, key in enumerate(("mu", "sigma", "rate")):
                plus, minus = list(parameters), list(parameters)
                h = 1e-6
                plus[index] += h
                minus[index] -= h
                numerical = (stable_roots(*plus).kappa - stable_roots(*minus).kappa) / (
                    2 * h
                )
                np.testing.assert_allclose(
                    numerical, root.kappa_derivatives[key], rtol=2e-8, atol=1e-9
                )


class HittingTests(unittest.TestCase):
    def test_closed_form_matches_independent_fpt_integration(self):
        for mu, sigma, gap, horizon, rate in (
            (0.7, 0.9, 1.3, 0.75, 0.4),
            (-0.6, 1.1, 1.7, 0.75, 0.2),
            (0.0, 0.5, 0.6, 0.75, 0.8),
            (1.2, 0.25, 0.4, 2.0, 0.0),
        ):
            value, gradient = hit_probability_and_gradient(
                gap, horizon, mu, sigma, rate=rate
            )
            numerical = quad(
                lambda t: math.exp(-rate * t) * float(fpt_density(t, gap, mu, sigma)),
                0,
                horizon,
                epsabs=1e-12,
                epsrel=1e-12,
            )[0]
            self.assertAlmostEqual(float(value), numerical, places=11)
            h = 1e-5
            q_lower = hit_probability_and_gradient(
                gap + h, horizon, mu, sigma, rate=rate
            )[0]
            q_upper = hit_probability_and_gradient(
                gap - h, horizon, mu, sigma, rate=rate
            )[0]
            np.testing.assert_allclose(
                gradient, (q_upper - q_lower) / (2 * h), rtol=2e-6, atol=1e-8
            )

    def test_killing_and_discount_are_distinct_readouts(self):
        base = hit_readout(0.8, 1.2, 0.3, 0.7, killing=0.1, discount=0)
        discounted = hit_readout(0.8, 1.2, 0.3, 0.7, killing=0.1, discount=0.5)
        self.assertEqual(float(base.probability), float(discounted.probability))
        self.assertLess(
            float(discounted.discounted_value), float(discounted.probability)
        )
        h = 1e-5
        plus = hit_readout(0.8, 1.2, 0.3, 0.7, killing=0.1 + h).probability
        minus = hit_readout(0.8, 1.2, 0.3, 0.7, killing=0.1 - h).probability
        reference = -quad(
            lambda t: t * math.exp(-0.1 * t) * float(fpt_density(t, 0.8, 0.3, 0.7)),
            0,
            1.2,
        )[0]
        self.assertAlmostEqual(float((plus - minus) / (2 * h)), reference, places=9)

    def test_vector_extremes_and_boundary_conventions(self):
        gap = np.array([-0.2, 0.0, 1e-6, 0.5, 8.0, 1.0])
        horizon = np.array([0.1, 0.1, 1e-7, 1.0, 0.02, 200.0])
        value, gradient = hit_probability_and_gradient(
            gap, horizon, 0.2, 0.6, rate=0.01
        )
        self.assertTrue(np.all(np.isfinite(gradient)))
        self.assertTrue(np.all((value >= 0) & (value <= 1)))
        self.assertTrue(np.all(gradient >= 0))
        self.assertEqual(float(value[0]), 1.0)
        self.assertEqual(float(gradient[0]), 0.0)
        self.assertGreater(float(gradient[1]), 0.0)
        with self.assertRaises(ValueError):
            hit_probability_and_gradient(0.2, 0.0, 0.2, 0.6)

    def test_score_integral_parameter_gradients(self):
        kwargs = dict(gap=0.7, horizon=1.2, mu=0.2, sigma=0.8, rate=0.1)
        derivatives = hit_sensitivities(**kwargs)
        for key in ("horizon", "mu", "sigma", "rate"):
            plus, minus = kwargs.copy(), kwargs.copy()
            plus[key] += 1e-5
            minus[key] -= 1e-5
            fd = (
                hit_probability_and_gradient(**plus)[0]
                - hit_probability_and_gradient(**minus)[0]
            ) / 2e-5
            np.testing.assert_allclose(fd, derivatives[key], rtol=2e-7, atol=1e-9)
        zero = hit_sensitivities(0.7, 1.2, 0.0, 0.8, rate=0.0)
        self.assertTrue(all(np.isfinite(v) for v in zero.values()))


class MovingBoundaryTests(unittest.TestCase):
    def test_fortet_linear_case_converges_to_exact_relative_drift(self):
        exact = linear_boundary_readout(
            0.0, 0.8, 0.2, 1.2, 0.3, 0.7, killing=0.1, discount=0.2
        )
        errors = []
        for n in (64, 128, 256, 512):
            answer = moving_boundary_reference(
                lambda t: 0.8 + 0.2 * t,
                0.0,
                1.2,
                0.3,
                0.7,
                killing=0.1,
                discount=0.2,
                steps=n,
            )
            errors.append(abs(answer.probability - float(exact.probability)))
            self.assertLess(answer.negative_mass, 1e-12)
        self.assertTrue(all(b < a for a, b in zip(errors, errors[1:])))
        self.assertLess(errors[-1], 3e-7)

    def test_curved_boundary_refinement_and_frozen_bias_are_reported(self):
        values = [
            moving_boundary_reference(
                lambda t: 0.8 + 0.2 * t + 0.1 * t * t,
                0.0,
                1.2,
                0.3,
                0.7,
                killing=0.1,
                steps=n,
            ).probability
            for n in (128, 256, 512)
        ]
        self.assertLess(abs(values[2] - values[1]), abs(values[1] - values[0]))
        self.assertLess(abs(values[2] - values[1]), 5e-7)
        frozen = float(hit_readout(0.8, 1.2, 0.3, 0.7, killing=0.1).probability)
        self.assertGreater(abs(frozen - values[-1]), 0.05)


if __name__ == "__main__":
    unittest.main()
