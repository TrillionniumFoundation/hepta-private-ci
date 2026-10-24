"""Narrow fail-closed regression candidate for an active subnormal scale."""

import unittest
from decimal import Decimal, localcontext

import numpy as np

from cell_field_retention import RetentionSolveError, retention_cost, solve_retention_tangent


def subnormal_problem():
    tiny = float(np.nextafter(0.0, 1.0))
    A = np.zeros((2, 1, 1))
    E = np.zeros_like(A)
    E[0, 0, 0] = 1e145
    C = np.zeros((3, 2, 1))
    C[1, 1, 0] = 1e170
    target = np.zeros((3, 2))
    target[1, 1] = -1e308
    return A, E, C, target, tiny, 1e308, np.zeros(1), 2 * tiny


class SubnormalRetentionRegression(unittest.TestCase):
    def test_diagnostic_rejects_materially_rounded_active_scale(self):
        tiny = float(np.nextafter(0.0, 1.0))
        with self.assertRaisesRegex(ValueError, "subnormal active retention"):
            retention_cost([[0.0, 1e308], [0.0, 0.0]], [[0.0]],
                           np.zeros((2, 2)), tiny, 1e308, old_weight=2 * tiny)

    def test_solver_cannot_certify_the_same_rounded_scale(self):
        A, E, C, target, dt, price, initial, weight = subnormal_problem()
        with self.assertRaises(RetentionSolveError) as caught:
            solve_retention_tangent(A, E, C, target, dt, price,
                                    initial=initial, old_weight=weight)
        receipt = caught.exception.receipt
        self.assertFalse(receipt["converged"])
        self.assertEqual(receipt["failure_stage"], "rollout")
        self.assertEqual(receipt["riccati_solve_attempts"], 0)
        self.assertEqual(receipt["line_search_evaluations"], 0)

    def test_zero_weight_and_exact_zero_hinge_remain_valid(self):
        A, E, C, target, dt, price, initial, weight = subnormal_problem()
        for tested_target, tested_weight in [(target, 0.0), (np.zeros_like(target), weight)]:
            with self.subTest(weight=tested_weight):
                result = solve_retention_tangent(A, E, C, tested_target, dt, price,
                                                initial=initial, old_weight=tested_weight)
                self.assertTrue(result["receipt"]["converged"])
                self.assertEqual(result["cost"]["total"], 0.0)
                np.testing.assert_array_equal(result["actions"], np.zeros((2, 1)))

    def test_supported_subnormal_inputs_with_normal_combined_root_still_work(self):
        tiny = float(np.nextafter(0.0, 1.0))
        for dt, weight, price in [(tiny, 1.0, 1e308), (1.0, tiny, 1.0)]:
            with self.subTest(dt=dt, weight=weight), localcontext() as context:
                context.prec = 100
                d = Decimal.from_float
                expected = float(d(dt) * d(weight) * d(1e100) ** 2 / 2)
                actual = retention_cost([[0.0, 1e100], [0.0, 0.0]], [[0.0]],
                                        np.zeros((2, 2)), dt, price, old_weight=weight)
                self.assertAlmostEqual(actual["retention_violation"] / expected, 1.0, places=13)

    def test_signed_scalar_active_pieces_against_closed_form(self):
        # Independent 16-case scalar formula, not the author's dense-mask oracle.
        for e in (-0.8, 1.2):
            for old_c in (-1.1, 0.6):
                for old_target in (-0.7, 0.4):
                    for current_target in (-0.5, 0.9):
                        dt, price, weight, base, current_c = 0.3, 0.7, 1.4, 0.16, 0.9
                        mu = dt * price
                        current_m, current_b = e * current_c, current_c * base - current_target
                        old_m, old_b = e * old_c, old_c * base - old_target
                        expected = -current_m * current_b / (mu + current_m**2)
                        if old_m * expected + old_b > 0:
                            expected = -(current_m * current_b + weight * old_m * old_b) / (
                                mu + current_m**2 + weight * old_m**2)
                        A, E = np.array([[[0.8]]]), np.array([[[e]]])
                        C = np.array([[[current_c], [old_c]], [[current_c], [old_c]]])
                        target = np.array([[0.0, 0.0], [current_target, old_target]])
                        result = solve_retention_tangent(A, E, C, target, dt, price,
                                                        initial=np.array([0.2]), old_weight=weight)
                        self.assertAlmostEqual(result["actions"][0, 0], expected, places=10)


if __name__ == "__main__":
    unittest.main()
