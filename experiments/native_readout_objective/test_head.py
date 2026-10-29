"""Numerical and arithmetic checks, never scientific confirmation samples."""

from fractions import Fraction
import unittest

import numpy as np

from .head import BOUND, Q, actions, fit, loss_and_grad, q24_scores


class HeadTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.Generator(np.random.Philox(991))
        self.x = rng.uniform(0.01, 0.8, (9, 20))
        self.q = np.column_stack((rng.normal(0, 2, (9, 2)), np.zeros(9)))
        self.weights = rng.normal(0, 0.1, (21, 2))

    def test_all_42_derivatives_match_independent_central_difference(self):
        for objective in ("q_mse", "policy_regret"):
            with self.subTest(objective=objective):
                _, analytic, _ = loss_and_grad(self.x, self.q, self.weights, objective)
                numeric = np.empty_like(analytic)
                for index in np.ndindex(self.weights.shape):
                    plus, minus = self.weights.copy(), self.weights.copy()
                    plus[index] += 1e-6
                    minus[index] -= 1e-6
                    numeric[index] = (
                        loss_and_grad(self.x, self.q, plus, objective)[0]
                        - loss_and_grad(self.x, self.q, minus, objective)[0]
                    ) / 2e-6
                np.testing.assert_allclose(analytic, numeric, rtol=2e-6, atol=3e-9)

    def test_regularization_excludes_bias_and_preserves_other_gradient_terms(self):
        for objective in ("q_mse", "policy_regret"):
            l0, g0, _ = loss_and_grad(
                self.x, self.q, self.weights, objective, penalty=0
            )
            l1, g1, _ = loss_and_grad(
                self.x, self.q, self.weights, objective, penalty=0.3
            )
            expected = np.zeros_like(self.weights)
            expected[:-1] = 0.6 * self.weights[:-1] / 40
            np.testing.assert_allclose(g1 - g0, expected, atol=1e-15)
            self.assertAlmostEqual(l1 - l0, 0.3 * np.mean(self.weights[:-1] ** 2))

    def test_mse_zero_data_error_and_ties(self):
        scores = np.column_stack(
            (np.column_stack((self.x, np.ones(9))) @ self.weights, np.zeros(9))
        )
        loss, gradient, _ = loss_and_grad(
            self.x, scores * 8, self.weights, "q_mse", penalty=0
        )
        self.assertEqual(loss, 0)
        np.testing.assert_array_equal(gradient, np.zeros((21, 2)))
        np.testing.assert_array_equal(
            actions([[0, 0, 0], [1, 1, 0], [1, 0, 1], [2, 1, 0]]), [2, 1, 2, 0]
        )

    def test_integer_readout_matches_fraction_reference_and_keeps_large_scores(self):
        rng = np.random.Generator(np.random.Philox(992))
        activations = rng.integers(0, 8 * Q + 1, (7, 20), dtype=np.int64)
        weights = rng.uniform(-BOUND, BOUND, (21, 2))
        expected = []
        for row in activations:
            out = []
            for j in range(2):
                out.append(
                    round(weights[-1, j] * Q)
                    + sum(
                        round(Fraction(int(value) * round(weights[k, j] * Q), Q))
                        for k, value in enumerate(row)
                    )
                )
            expected.append(out + [0])
        np.testing.assert_array_equal(q24_scores(activations, weights), expected)
        full = q24_scores(
            np.full((1, 20), 8 * Q, dtype=np.int64), np.full((21, 2), BOUND)
        )
        np.testing.assert_array_equal(full, [[round(1207.5 * Q), round(1207.5 * Q), 0]])

    def test_signed_half_ties_are_rounded_per_product_before_addition(self):
        activation = np.zeros((1, 20), dtype=np.int64)
        activation[0, :4] = Q // 2
        weights = np.zeros((21, 2))
        weights[:4, 0] = np.array([1, 1, 3, 5]) / Q
        weights[:4, 1] = -weights[:4, 0]
        np.testing.assert_array_equal(q24_scores(activation, weights), [[4, -4, 0]])
        # Coefficient encoding itself also has ties-even, as make_profile uses.
        weights[:] = 0
        weights[-1] = [0.5 / Q, 1.5 / Q]
        np.testing.assert_array_equal(q24_scores(activation, weights), [[0, 2, 0]])

    def test_fit_improves_both_losses_and_is_deterministic(self):
        for objective in ("q_mse", "policy_regret"):
            a, receipt = fit(self.x, self.q, objective, learning_rate=0.02)
            b, again = fit(self.x, self.q, objective, learning_rate=0.02)
            np.testing.assert_array_equal(a, b)
            self.assertLess(receipt["final_loss"], receipt["initial_loss"])
            self.assertEqual(receipt["epoch_loss"], again["epoch_loss"])
            self.assertEqual(receipt["coordinates_with_nonzero_gradient"], 42)
            self.assertEqual(len(receipt["epoch_loss"]), 120)
            self.assertTrue(np.all(np.abs(a) <= BOUND))

    def test_bad_data_cannot_silently_change_the_training_domain(self):
        cases = [
            (self.x - 10, self.q),
            (self.x, self.q[:, :2]),
            (self.x[:0], self.q[:0]),
            (self.x * np.nan, self.q),
        ]
        nonzero_stop = self.q.copy()
        nonzero_stop[:, 2] = 1
        cases.append((self.x, nonzero_stop))
        for x, q in cases:
            with self.assertRaises(ValueError):
                fit(x, q, "q_mse", learning_rate=0.02)
        with self.assertRaises(ValueError):
            q24_scores(np.ones((1, 20)), self.weights)
        with self.assertRaises(ValueError):
            loss_and_grad(self.x, self.q, np.full((21, 2), 8), "q_mse")


if __name__ == "__main__":
    unittest.main()
