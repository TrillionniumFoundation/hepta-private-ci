"""Independent finite games, observational limits, and analytic BSDE checks."""

from itertools import product
import math
import unittest

import numpy as np

from risk import (Transition, binomial_entropic_step, conditional_rows, entropic_ce,
                  gaussian_entropic_bsde, rectangular_bellman, robust_ce,
                  validate_probabilities)


class RiskTests(unittest.TestCase):
    def test_entropic_sign_translation_and_extreme_finite_inputs(self):
        expected = -math.log(.3 * math.exp(2) + .7 * math.exp(-4)) / 2
        self.assertAlmostEqual(entropic_ce([-1, 2], [.3, .7], 2), expected, places=14)
        self.assertAlmostEqual(entropic_ce([16, 19], [.3, .7], 2), expected + 17, places=13)
        self.assertEqual(entropic_ce([-1e308, 2], [0, 1], 1e308), 2)
        self.assertEqual(entropic_ce([-.5, -2], [.5, .5], 1e308), -2)
        self.assertAlmostEqual(entropic_ce([-1, 2], [.3, .7], 1e-300), 1.1, places=14)
        self.assertTrue(math.isfinite(entropic_ce([-1e308, 1e308], [5e-324, 1], 1e-308)))
        self.assertEqual(entropic_ce([-1e308, 1e308], [.5, .5], 0), 0)
        batched = entropic_ce([[1, 2], [3, 4]], [.5, .5], 2)
        np.testing.assert_allclose(batched[1] - batched[0], 2, rtol=0, atol=1e-14)

    def test_probability_and_risk_rejection(self):
        for bad in ([], [0, 0], [.2, .2], [-1, 2], [float("nan"), 1], [1, float("inf")]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_probabilities(bad)
        for bad in (-1, float("inf"), float("nan"), True, [1]):
            with self.subTest(gamma=bad), self.assertRaises(ValueError):
                entropic_ce([1, 2], [.5, .5], bad)
        with self.assertRaises(ValueError):
            robust_ce([1, 2], [.5, .5], 1)

    def test_ambiguity_convex_hull_and_worst_row(self):
        rows = np.array([[.8, .2], [.2, .8]])
        values = np.array([[0, 1], [2, -1]])
        value, index = robust_ce(values, rows, .7, return_worst=True)
        np.testing.assert_array_equal(index, [0, 1])
        for mixing in np.linspace(0, 1, 31):
            self.assertTrue(np.all(entropic_ce(values, mixing * rows[0] + (1 - mixing) * rows[1], .7) >= value - 1e-14))

    def test_same_marginals_different_dependence_and_history_support(self):
        models = np.array([[[.5, 0], [0, .5]], [[0, .5], [.5, 0]]])
        np.testing.assert_array_equal(models.sum(axis=1), [[.5, .5], [.5, .5]])
        np.testing.assert_array_equal(models.sum(axis=2), [[.5, .5], [.5, .5]])
        rows, active = conditional_rows(models, (None, 0), 0, return_models=True)
        np.testing.assert_array_equal(rows, [[1, 0], [0, 1]])
        self.assertEqual(active, (0, 1))
        self.assertEqual(robust_ce([1, 0], rows, 2), 0)
        self.assertEqual(entropic_ce([1, 0], rows[0], 2), 1)
        sparse = np.zeros((2, 2, 3))
        sparse[0, 0, 0], sparse[1, 1, 1] = 1, 1
        _, active = conditional_rows(sparse, (None, 1), 0, return_models=True)
        self.assertEqual(active, (1,))
        with self.assertRaises(ValueError):
            conditional_rows(sparse, (None, 2), 0)
        with self.assertRaises(ValueError):
            conditional_rows(sparse, (0, None), 0)

    def test_bellman_matches_full_control_and_nature_policy_enumeration(self):
        root_rows = np.array([[.5, .5], [.2, .8]])
        left_rows = np.array([[.9, .1], [.4, .6]])
        right_rows = np.array([[.1, .9], [.7, .3]])
        layers = [('root',), ('left', 'right', 'safe'), ('zero', 'one')]
        actions = {
            (0, 'root'): (Transition('continue', ('left', 'right'), root_rows, -.03),
                          Transition('stop', ('safe',), [[1]])),
            (1, 'left'): (Transition('risky', ('zero', 'one'), left_rows),
                          Transition('safe', ('zero',), [[1]], .2)),
            (1, 'right'): (Transition('risky', ('zero', 'one'), right_rows),
                           Transition('safe', ('zero',), [[1]], .15)),
            (1, 'safe'): (Transition('finish', ('zero',), [[1]], .16),),
        }
        for gamma in (0, .7, 3):
            policy_values = []
            for root, left, right in product(range(2), repeat=3):
                adversarial_values = []
                for nature_root, nature_left, nature_right in product(range(2), repeat=3):
                    outcomes = []
                    if root == 1:
                        outcomes = [(1., .16)]
                    else:
                        for branch, decision, laws, nature, safe in (
                                (0, left, left_rows, nature_left, .2),
                                (1, right, right_rows, nature_right, .15)):
                            probability = root_rows[nature_root, branch]
                            outcomes.extend([(probability, safe - .03)] if decision else
                                            [(probability * p, float(reward) - .03)
                                             for reward, p in enumerate(laws[nature])])
                    value = (sum(p * reward for p, reward in outcomes) if gamma == 0 else
                             -math.log(sum(p * math.exp(-gamma * reward) for p, reward in outcomes)) / gamma)
                    adversarial_values.append(value)
                policy_values.append(min(adversarial_values))
            solution = rectangular_bellman(layers, actions, {'zero': 0, 'one': 1}, gamma)
            self.assertAlmostEqual(solution.values[(0, 'root')], max(policy_values), places=13)

    def test_rectangle_is_strictly_larger_than_fixed_regime_set(self):
        layers = [('root',), ('left', 'right'), ('zero', 'one')]
        actions = {(0, 'root'): (Transition('only', ('left', 'right'), [[.5, .5]]),),
                   (1, 'left'): (Transition('only', ('zero', 'one'), [[1, 0], [0, 1]]),),
                   (1, 'right'): (Transition('only', ('zero', 'one'), [[0, 1], [1, 0]]),)}
        value = rectangular_bellman(layers, actions, {'zero': 0, 'one': 1}, 2).values[(0, 'root')]
        self.assertEqual(value, 0)
        static_regime_value = -math.log((1 + math.exp(-2)) / 2) / 2
        self.assertGreater(static_regime_value, value)
        with self.assertRaises(ValueError):
            rectangular_bellman(layers, {}, {'zero': 0, 'one': 1}, 2)

    def test_symmetric_shared_wrong_bound_and_new_information(self):
        joint = (np.ones((8, 8)) - np.eye(8)) / 56  # truth, common observed label
        self.assertAlmostEqual(joint.max(axis=0).sum(), 1 / 7, places=14)
        correct_world = np.eye(8) / 8
        np.testing.assert_allclose(joint.sum(axis=0), correct_world.sum(axis=0))
        # A separate perfect verifier enlarges the information set. It is not
        # a different interpretation of the original eight-label observation.
        verified = joint[:, :, None] * np.eye(8)[:, None, :]
        self.assertAlmostEqual(verified.max(axis=0).sum(), 1, places=14)

    def test_gaussian_closed_form_quadrature_and_parameter_gradient_separation(self):
        gamma, sigma, mu, time, horizon, w = .7, 1.2, .4, .4, 1.3, .1
        utility, z = gaussian_entropic_bsde(time, w, horizon, mu, sigma, gamma)
        self.assertAlmostEqual(utility, .0664, places=14)
        self.assertEqual(z, sigma)
        nodes, weights = np.polynomial.hermite.hermgauss(48)
        next_u, _ = gaussian_entropic_bsde(time + .3, w + np.sqrt(.6) * nodes,
                                         horizon, mu, sigma, gamma)
        self.assertAlmostEqual(entropic_ce(next_u, weights / np.sqrt(np.pi), gamma), utility, places=12)
        epsilon = 1e-6
        plus = gaussian_entropic_bsde(time, w, horizon, mu, sigma + epsilon, gamma)[0]
        minus = gaussian_entropic_bsde(time, w, horizon, mu, sigma - epsilon, gamma)[0]
        parameter_gradient = (plus - minus) / (2 * epsilon)
        self.assertAlmostEqual(parameter_gradient, w - gamma * sigma * (horizon - time), places=9)
        self.assertGreater(abs(parameter_gradient - z), 1)

    def test_binomial_decomposition_and_quadratic_driver_limit(self):
        gamma, z = 1.3, .7
        errors = []
        for dt in (1 / 16, 1 / 64, 1 / 256):
            step = binomial_entropic_step(-z * math.sqrt(dt), z * math.sqrt(dt), dt, gamma)
            self.assertAlmostEqual(step.z, z, places=14)
            for sign in (-1, 1):
                self.assertAlmostEqual(step.utility - step.driver * dt + step.z * sign * math.sqrt(dt),
                                       sign * z * math.sqrt(dt), places=14)
            errors.append(abs(step.driver + gamma * z ** 2 / 2))
        self.assertTrue(errors[2] < errors[1] / 3 < errors[0] / 9)


if __name__ == '__main__':
    unittest.main()
