"""Analytic and independent dense-oracle tests; no model/data execution."""

import itertools
import unittest
from decimal import Decimal, localcontext

import numpy as np

from cell_field_control import quadratic_cost, solve_lq
from cell_field_retention import (
    RetentionSolveError, retention_cost, retention_targets, retention_tangent_evaluate,
    retention_violation, solve_retention_tangent,
)


def scalar_problem(desired=1.0, threshold=0.2):
    return (np.ones((1, 1, 1)), np.ones((1, 1, 1)), np.ones((2, 2, 1)),
            np.array([[0.0, threshold], [desired, threshold]]), np.zeros(1))


def dense_mask_oracle(A, E, C, target, initial, dt, effort_price, old_weight):
    """Independent condensing + exhaustive masks. Does not call production code."""
    horizon, dim, act = len(A), len(initial), E.shape[2]
    variables = horizon * act
    base = np.empty((horizon + 1, dim))
    base[0] = initial
    response = np.zeros((horizon + 1, dim, variables))
    for k in range(horizon):
        base[k + 1] = A[k] @ base[k]
        response[k + 1] = A[k] @ response[k]
        response[k + 1, :, k * act:(k + 1) * act] += E[k]
    design = np.einsum("kij,kjl->kil", C, response)
    intercept = np.einsum("kij,kj->ki", C, base) - target
    time_weights = np.r_[np.full(horizon, dt), 1.0]
    accepted = []
    for bits in itertools.product((0, 1), repeat=horizon + 1):
        weights = time_weights[:, None] * np.column_stack((np.ones(horizon + 1), old_weight * np.array(bits)))
        H = dt * effort_price * np.eye(variables) + np.einsum("koi,ko,koj->ij", design, weights, design)
        b = np.einsum("koi,ko,ko->i", design, weights, intercept)
        controls = np.linalg.solve(H, -b)
        errors = np.einsum("koi,i->ko", design, controls) + intercept
        if any((e < -1e-8 if bit else e > 1e-8) for e, bit in zip(errors[:, 1], bits)):
            continue
        value = 0.5 * (time_weights @ (errors[:, 0] ** 2 + old_weight * np.maximum(errors[:, 1], 0) ** 2)
                       + dt * effort_price * (controls @ controls))
        accepted.append((float(value), controls.reshape(horizon, act)))
    if not accepted:
        raise AssertionError("independent exhaustive oracle found no consistent piece")
    return min(accepted, key=lambda value: value[0])


class RetentionTests(unittest.TestCase):
    def test_improvement_tolerance_and_active_loss_derivative(self):
        losses = np.array([0.5, 1.0, 1.125, 1.25, 1.5])
        result = retention_violation(losses, anchor=1.0, tolerance=0.25, weight=2.0)
        np.testing.assert_allclose(result["penalty"], [0, 0, 0, 0, 0.0625], rtol=0, atol=1e-16)
        np.testing.assert_array_equal(result["derivative"], [0, 0, 0, 0, 0.5])
        np.testing.assert_array_equal(result["at_threshold"], [False, False, False, True, False])
        np.testing.assert_array_equal(result["chosen_generalized_curvature"], [0, 0, 0, 0, 2])
        eps = 1e-5
        def f(x):
            return float(retention_violation(x, anchor=1.0, tolerance=0.25, weight=2.0)["penalty"])

        self.assertAlmostEqual((f(1.5 + eps) - f(1.5 - eps)) / (2 * eps), 0.5, places=9)
        self.assertAlmostEqual(2 * f(1.25 - eps) / eps**2, 0.0, places=8)
        self.assertAlmostEqual(2 * f(1.25 + eps) / eps**2, 2.0, places=8)

    def test_frozen_anchor_translation_and_suffix_prevents_ratcheting(self):
        reference = np.array([[2.0, 1.0], [1.8, 1.2], [1.7, 0.7], [1.6, 1.5]])
        target = retention_targets(reference, -0.03, anchor=1.0, tolerance=0.1)
        np.testing.assert_allclose(target[:, 1] + reference[:, 1], np.full(4, 1.1))
        for k in (1, 2):
            suffix = retention_targets(reference[k:], -0.03, anchor=1.0, tolerance=0.1)
            np.testing.assert_array_equal(suffix, target[k:])
        self.assertAlmostEqual(float(retention_violation(1.25, anchor=1.0, tolerance=0.1)["violation"]), 0.15)
        # Resetting the anchor to 1.2 would erase this penalty; the API never does it.

    def test_scalar_closed_form_improving_tolerance_active_and_boundary(self):
        price, weight = 0.5, 2.0
        for desired, threshold in [(-1, 0.0), (0.2, 0.5), (1.0, 0.2), (0.375, 0.25)]:
            with self.subTest(desired=desired, threshold=threshold):
                A, E, C, target, initial = scalar_problem(desired, threshold)
                unconstrained = desired / (1 + price)
                expected = (unconstrained if unconstrained <= threshold
                            else (desired + weight * threshold) / (1 + price + weight))
                result = solve_retention_tangent(A, E, C, target, 1.0, price, initial=initial, old_weight=weight)
                self.assertAlmostEqual(result["actions"][0, 0], expected, places=10)
                self.assertLessEqual(result["receipt"]["gradient_inf"], 1e-9)
                self.assertFalse(result["receipt"]["global_affine_feedback"])
                self.assertFalse(result["receipt"]["hard_retention_constraint"])
                self.assertNotIn("K", result)

    def test_crossing_hinge_requires_true_objective_backtracking(self):
        A, E, C, target, initial = scalar_problem(1.0, 0.1)
        result = solve_retention_tangent(A, E, C, target, 1.0, 0.1, initial=initial, old_weight=100.0)
        self.assertAlmostEqual(result["actions"][0, 0], 11 / 101.1, places=10)
        self.assertGreater(result["receipt"]["line_search_evaluations"], result["receipt"]["riccati_solve_attempts"])
        values = [r["cost"] for r in result["receipt"]["trace"]]
        self.assertTrue(all(b <= a + 1e-13 for a, b in zip(values, values[1:])))

    def test_adjoint_gradient_and_local_piece_curvature_by_finite_difference(self):
        rng = np.random.default_rng(17)
        A = rng.normal(0, 0.3, (3, 2, 2))
        E = rng.normal(0, 0.4, (3, 2, 2))
        C = rng.normal(0, 1, (4, 2, 2))
        target = rng.normal(0, 0.7, (4, 2))
        initial, actions = rng.normal(size=2), rng.normal(size=(3, 2))
        def evaluate(u):
            return retention_tangent_evaluate(A, E, C, target, initial, u, 0.2, 0.7, old_weight=1.3)

        center = evaluate(actions)
        self.assertGreater(np.min(np.abs(center["old_excess"])), 1e-3)
        eps = 1e-5
        direction = rng.normal(size=actions.shape)
        plus, minus = evaluate(actions + eps * direction), evaluate(actions - eps * direction)
        numerical = (plus["cost"]["total"] - minus["cost"]["total"]) / (2 * eps)
        self.assertAlmostEqual(numerical, float(np.sum(center["gradient"] * direction)), places=8)
        hessian_direction = (plus["gradient"] - minus["gradient"]) / (2 * eps)
        second_cost = (plus["cost"]["total"] - 2 * center["cost"]["total"] + minus["cost"]["total"]) / eps**2
        self.assertAlmostEqual(second_cost, float(np.sum(direction * hessian_direction)), delta=2e-4)
        self.assertGreaterEqual(float(np.sum(direction * hessian_direction)),
                                0.2 * 0.7 * float(np.square(direction).sum()) - 1e-9)

    def test_multistep_time_varying_systems_against_independent_exhaustive_oracle(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                rng = np.random.default_rng(seed)
                A = rng.normal(0, 0.4, (3, 2, 2))
                E = rng.normal(0, 0.5, (3, 2, 2))
                C = rng.normal(0, 0.8, (4, 2, 2))
                target = rng.normal(0, 0.6, (4, 2))
                initial = rng.normal(0, 0.3, 2)
                values = [v.copy() for v in (A, E, C, target, initial)]
                expected_cost, expected_actions = dense_mask_oracle(A, E, C, target, initial, 0.2, 0.4, 1.7)
                actual = solve_retention_tangent(A, E, C, target, 0.2, 0.4, initial=initial, old_weight=1.7)
                np.testing.assert_allclose(actual["actions"], expected_actions, atol=2e-8, rtol=2e-8)
                self.assertAlmostEqual(actual["cost"]["total"], expected_cost, places=11)
                for before, after in zip(values, (A, E, C, target, initial)):
                    np.testing.assert_array_equal(before, after)

    def test_all_active_and_disabled_retention_reduce_to_corresponding_lq(self):
        for weight, threshold in [(2.3, -10.0), (0.0, 0.2)]:
            A, E, C, target, initial = scalar_problem(1.0, threshold)
            result = solve_retention_tangent(A, E, C, target, 0.3, 0.4, initial=initial, old_weight=weight)
            scaled_C, scaled_target = C.copy(), target.copy()
            scaled_C[:, 1] *= np.sqrt(weight); scaled_target[:, 1] *= np.sqrt(weight)
            legacy = solve_lq(A, E, scaled_C, scaled_target, 0.3, 0.4)
            expected = -legacy["K"][0] @ initial + legacy["offset"][0]
            np.testing.assert_allclose(result["actions"][0], expected, atol=1e-10)
            value = quadratic_cost(np.einsum("kij,kj->ki", scaled_C, result["states"]),
                                   result["actions"], scaled_target, 0.3, 0.4)
            self.assertAlmostEqual(result["cost"]["total"], value["total"], places=10)

    def test_published_quadratic_objective_stays_distinct_and_unchanged(self):
        fields = np.array([[0, 0], [0, -0.5]], dtype=float)
        actions, target = np.zeros((1, 1)), np.zeros((2, 2))
        old = quadratic_cost(fields, actions, target, 0.2, 0.1)
        new = retention_cost(fields, actions, target, 0.2, 0.1)
        self.assertEqual(old, {"total": 0.125, "tracking": 0.125, "effort": 0.0})
        self.assertEqual(new, {"total": 0.0, "current_tracking": 0.0, "retention_violation": 0.0, "effort": 0.0})

    def test_budget_exhaustion_is_failure_and_inputs_stay_unchanged(self):
        A, E, C, target, initial = scalar_problem(1.0, 0.1)
        originals = [v.copy() for v in (A, E, C, target, initial)]
        with self.assertRaises(RetentionSolveError) as caught:
            solve_retention_tangent(A, E, C, target, 1.0, 0.1, initial=initial,
                                    old_weight=100.0, max_iterations=1)
        self.assertFalse(caught.exception.receipt["converged"])
        self.assertEqual(caught.exception.receipt["reason"], "iteration budget exhausted")
        self.assertEqual(caught.exception.receipt["iterations"], 1)
        for before, after in zip(originals, (A, E, C, target, initial)):
            np.testing.assert_array_equal(before, after)

    def test_invalid_objective_shapes_nonfinite_and_work_budget_are_rejected(self):
        for options in [dict(anchor=-1, tolerance=0), dict(anchor=1, tolerance=-0.1),
                        dict(anchor=1, tolerance=float("inf")), dict(anchor=1, tolerance=0, weight=-1)]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                retention_violation([1.0], **options)
        A, E, C, target, initial = scalar_problem()
        for price in [0.0, -1.0, float("nan"), float("inf"), True]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                solve_retention_tangent(A, E, C, target, 0.2, price, initial=initial)
        with self.assertRaises(ValueError):
            solve_retention_tangent(A, E, C[:, :1], target, 0.2, 1, initial=initial)
        with self.assertRaises(ValueError):
            solve_retention_tangent(A, E, C, np.full_like(target, np.nan), 0.2, 1, initial=initial)
        with self.assertRaises(ValueError):
            solve_retention_tangent(np.zeros((65, 1, 1)), np.zeros((65, 1, 1)),
                np.zeros((66, 2, 1)), np.zeros((66, 2)), 0.2, 1, initial=np.zeros(1))
        with self.assertRaises(ValueError):
            solve_retention_tangent(np.zeros((8, 512, 512)), np.zeros((8, 512, 1)),
                np.zeros((9, 2, 512)), np.zeros((9, 2)), 0.2, 1, initial=np.zeros(512))

    def test_list_inputs_and_real_scalar_admission(self):
        A, E, C, target, initial = scalar_problem()
        arguments = [v.tolist() for v in (A, E, C, target, initial)]
        actual = retention_tangent_evaluate(*arguments, [[0.0]], 0.2, 0.1)
        expected = retention_tangent_evaluate(A, E, C, target, initial, np.zeros((1, 1)), 0.2, 0.1)
        np.testing.assert_array_equal(actual["gradient"], expected["gradient"])
        for value in [1 + 0j, np.complex128(1), "1", True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                retention_violation([1], anchor=value, tolerance=0)
        with self.assertRaises(ValueError):
            retention_violation([1 + 1j], anchor=1, tolerance=0)

    def test_arithmetic_overflow_and_underflow_reject_instead_of_certifying(self):
        A, E, C, target, initial = scalar_problem()
        with self.assertRaises(ValueError):
            solve_retention_tangent(A, E, C, np.zeros_like(target), 1e-300, 1e-300, initial=initial)
        with self.assertRaises(ValueError):
            retention_targets(np.zeros((2, 2)), 0, anchor=1e308, tolerance=1e308)
        with self.assertRaises(ValueError):
            retention_violation([1e308], anchor=0, tolerance=0)
        disabled = retention_violation([1e308], anchor=0, tolerance=0, weight=0)
        np.testing.assert_array_equal(disabled["penalty"], [0])
        with self.assertRaises(RetentionSolveError) as caught:
            solve_retention_tangent(A, E, C, np.full_like(target, 1e200), 0.2, 0.1, initial=initial)
        receipt = caught.exception.receipt
        self.assertFalse(receipt["converged"])
        self.assertEqual(receipt["failure_stage"], "rollout")
        self.assertEqual(receipt["riccati_solve_attempts"], 0)
        self.assertGreater(receipt["wall_ns"], 0)

    def test_nonfinite_trials_spend_bounded_budget_and_preserve_failure_receipt(self):
        A, E, C, target, initial = scalar_problem(1e150, 0.1)
        with self.assertRaises(RetentionSolveError) as caught:
            solve_retention_tangent(A, E, C, target, 1.0, 1.0, initial=initial, old_weight=1e100)
        receipt = caught.exception.receipt
        self.assertFalse(receipt["converged"])
        self.assertEqual(receipt["failure_stage"], "line_search")
        self.assertEqual(receipt["riccati_solve_attempts"], 1)
        self.assertEqual(receipt["line_search_evaluations"], 40)
        self.assertGreater(receipt["cpu_ns"], 0)

    def test_certificate_does_not_erase_a_representable_bound_by_squaring_first(self):
        A, E, C, target, initial = scalar_problem(1e-100, 1.0)
        C[:, 0] = 1e-100
        result = solve_retention_tangent(A, E, C, target, 1.0, 1e-300, initial=initial)
        self.assertAlmostEqual(result["receipt"]["numerical_suboptimality_bound"] / 5e-101, 1.0, places=12)

    def test_root_review_weight_product_underflow_keeps_representable_cost(self):
        fields, actions, target = np.array([[0, 1e150], [0, 0]]), np.zeros((1, 1)), np.zeros((2, 2))
        actual = retention_cost(fields, actions, target, 1e-200, 1e200, old_weight=1e-200)
        with localcontext() as context:
            context.prec = 100
            d = Decimal.from_float
            expected = float(d(1e-200) * d(1e-200) * d(1e150) ** 2 / 2)
        self.assertAlmostEqual(actual["retention_violation"] / expected, 1.0, places=13)
        self.assertEqual(actual["retention_violation"], actual["total"])
        disabled = retention_cost(fields, actions, target, 1e-200, 1e200, old_weight=0)
        self.assertEqual(disabled["retention_violation"], 0.0)
        with self.assertRaises(ValueError):
            retention_cost([[0, 1e-200], [0, 0]], actions, target, 1.0, 1.0)
        with self.assertRaises(ValueError):
            retention_violation([1e-200], anchor=0, tolerance=0)

    def test_gradient_uses_same_scaled_residual_as_cost(self):
        A, E, C, target, initial = scalar_problem(0.0, -1e150)
        C[:, 1] = 1e-200
        result = retention_tangent_evaluate(A, E, C, target, initial, np.zeros((1, 1)),
                                           1.0, 1.0, old_weight=1e-200)
        self.assertAlmostEqual(result["gradient"][0, 0] / 1e-250, 1.0, places=13)
        self.assertAlmostEqual(result["cost"]["retention_violation"] / 1e100, 1.0, places=13)

    def test_unsupported_active_old_curvature_rejects_before_small_gradient_success(self):
        A, E, C, target, initial = scalar_problem(0.0, -1e150)
        C[:, 1] = 1e-200  # current C=1 must not hide the erased old quadratic row
        with self.assertRaises(RetentionSolveError) as caught:
            solve_retention_tangent(A, E, C, target, 1.0, 1.0, initial=initial, old_weight=1e-200)
        receipt = caught.exception.receipt
        self.assertFalse(receipt["converged"])
        self.assertEqual(receipt["failure_stage"], "quadratic_scale")
        self.assertLess(receipt["gradient_inf"], receipt["gradient_tolerance"])
        self.assertEqual(receipt["riccati_solve_attempts"], 0)

    def test_stable_norm_preserves_representable_sum_of_tiny_penalties(self):
        fields = np.zeros((65, 2))
        fields[:, 1] = 1e-162
        actual = retention_cost(fields, np.zeros((64, 1)), np.zeros((65, 2)), 1.0, 1.0)
        with localcontext() as context:
            context.prec = 100
            expected = float(Decimal(65) * Decimal.from_float(1e-162) ** 2 / 2)
        self.assertGreater(expected, 0)
        self.assertEqual(actual["retention_violation"], expected)


if __name__ == "__main__":
    unittest.main()
