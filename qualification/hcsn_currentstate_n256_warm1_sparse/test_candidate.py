"""Tiny numerical controls only; no authentic N256 propagation in tests."""

import math
import unittest

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import issparse

from qualification.hcsn_currentstate_n256_warm1_sparse.candidate import calculate


class TinyControls(unittest.TestCase):
    def test_nonuniform_signed_channels_against_independent_ode(self):
        nodes = np.array([0.0, 0.2, 0.5, 0.9, 1.4])
        active = np.array([[0.2, 0.3, 0.1], [-0.4, 0.1, 0.2]])
        parent, upper = np.array([0.13, -0.07]), np.array([0.04, -0.02])
        mu, sigma, reset, duration, discount = -0.06, 0.3, 0.4, 0.037, 0.17
        state, generator, alpha, output, residual, actions, balances = calculate(
            nodes, active, upper, parent, mu, sigma, reset, duration, discount)
        self.assertTrue(issparse(generator))
        self.assertEqual([item["order"] for item in actions], [6, 7])
        q, low, high = np.zeros((3, 3)), np.zeros(3), np.zeros(3)
        for j in range(3):
            left, right = nodes[j + 1] - nodes[j], nodes[j + 2] - nodes[j + 1]
            down = (sigma * sigma - mu * right) / (left * (left + right))
            up = (sigma * sigma + mu * left) / (right * (left + right))
            q[j, j] = -down - up
            if j:
                q[j, j - 1] = down
            else:
                low[j] = down
            if j < 2:
                q[j, j + 1] = up
            else:
                high[j] = up
        weights = np.array([1 / 3, 2 / 3, 0.0])

        def rhs(t, y):
            y = y.reshape(2, 7)
            a = y[:, :3]
            return np.column_stack((a @ q + parent[:, None] * weights,
                                    a @ high, a @ low, math.exp(-discount * t) * (a @ low),
                                    math.exp(-discount * t) * (a.sum(axis=1) + y[:, 3]))).ravel()

        y0 = np.column_stack((active, np.zeros((2, 4)))).ravel()
        answer = solve_ivp(rhs, (0, duration), y0, rtol=2e-12, atol=2e-14, method="DOP853").y[:, -1].reshape(2, 7)
        np.testing.assert_allclose(state["active"][:, 0], answer[:, :3], atol=3e-13, rtol=3e-12)
        np.testing.assert_allclose(state["upper"][:, 1], answer[:, 3], atol=3e-13, rtol=3e-12)
        np.testing.assert_allclose(state["mass"][:, 0], answer[:, 4], atol=3e-13, rtol=3e-12)
        np.testing.assert_allclose(state["discounted_hit"][:, 0], answer[:, 5], atol=3e-13, rtol=3e-12)
        np.testing.assert_allclose(state["occupation"][:, 1], answer[:, 6], atol=3e-13, rtol=3e-12)
        np.testing.assert_allclose(state["occupation"][:, 0], upper * -math.expm1(-discount * duration) / discount)
        np.testing.assert_allclose(balances, 0, atol=3e-16)
        np.testing.assert_allclose(residual[:, 0], parent, atol=1e-16)
        np.testing.assert_array_equal(alpha, np.column_stack((parent, active)))
        np.testing.assert_array_equal(output, np.r_[0.0, low])

    def test_zero_law_and_invalid_reset(self):
        state, _, _, _, _, _, balance = calculate([0, 0.2, 0.5, 0.9], np.zeros((1, 2)),
                                                  np.zeros(1), np.zeros(1), 0, 0.3, 0.3, 0.001, 0.15)
        for values in state.values():
            np.testing.assert_array_equal(values, np.zeros_like(values))
        self.assertEqual(balance, [0.0])
        with self.assertRaisesRegex(ValueError, "interior reset"):
            calculate([0, 0.2, 0.5, 0.9], np.zeros((1, 2)), np.zeros(1), np.zeros(1), 0, 0.3, 0.1, 0.001, 0.15)


if __name__ == "__main__":
    unittest.main()
