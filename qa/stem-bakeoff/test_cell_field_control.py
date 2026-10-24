"""Independent quadratic solve and actual-head integration checks."""

import unittest

import numpy as np

from cell_field_control import (build_reference, diagnose_tangent, fit_controller,
                                quadratic_cost, run_nonlinear, solve_lq)
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class QuadraticControlTests(unittest.TestCase):
    def test_riccati_matches_independent_condensed_least_squares(self):
        rng = np.random.default_rng(203)
        horizon, dim, actions = 5, 3, 2
        A = np.array([0.7 * np.eye(dim) + rng.normal(0, 0.05, (dim, dim)) for _ in range(horizon)])
        E = rng.normal(0, 0.2, (horizon, dim, actions))
        C = rng.normal(0, 0.4, (horizon + 1, 2, dim))
        target = rng.normal(0, 0.1, (horizon + 1, 2))
        initial, dt, price = np.array([0.2, -0.1, 0.3]), 0.2, 0.7
        policy = solve_lq(A, E, C, target, dt, price)

        def residual(flat):
            u = flat.reshape(horizon, actions)
            x, rows = initial.copy(), []
            for k in range(horizon):
                rows.extend(np.sqrt(dt) * (C[k] @ x - target[k]))
                x = A[k] @ x + E[k] @ u[k]
            rows.extend(C[-1] @ x - target[-1])
            rows.extend(np.sqrt(dt * price) * flat)
            return np.array(rows)

        zero = np.zeros(horizon * actions)
        offset = residual(zero)
        matrix = np.stack([residual(row) - offset for row in np.eye(len(zero))], axis=1)
        expected = np.linalg.lstsq(matrix, -offset, rcond=None)[0]
        x, observed = initial.copy(), []
        for k in range(horizon):
            u = -policy["K"][k] @ x + policy["offset"][k]
            observed.extend(u)
            x = A[k] @ x + E[k] @ u
        np.testing.assert_allclose(observed, expected, atol=2e-13, rtol=2e-12)
        initial_value = (0.5 * initial @ policy["P"][0] @ initial
                         + policy["ell"][0] @ initial + policy["constant"][0])
        self.assertAlmostEqual(initial_value, 0.5 * residual(expected) @ residual(expected), places=13)

    def test_bellman_advantage_for_arbitrary_occupancy(self):
        A = np.tile(np.array([[0.8, 0.2], [0.1, 0.9]]), (4, 1, 1))
        E = np.tile(np.array([[0.2], [0.05]]), (4, 1, 1))
        C = np.tile(np.eye(2), (5, 1, 1))
        target = np.array([-0.1, 0.03])
        oracle = solve_lq(A, E, C, target, 0.1, 0.3)
        initial = np.array([0.2, -0.1])
        states, actions, advantage = [initial], [], 0.0
        for k in range(4):
            u = np.array([0.03 * (k + 1)])
            optimum = -oracle["K"][k] @ states[-1] + oracle["offset"][k]
            advantage += 0.5 * (u - optimum) @ oracle["W"][k] @ (u - optimum)
            actions.append(u)
            states.append(A[k] @ states[-1] + E[k] @ u)
        actual = quadratic_cost(np.array(states), np.array(actions), target, 0.1, 0.3)["total"]
        value = 0.5 * initial @ oracle["P"][0] @ initial + oracle["ell"][0] @ initial + oracle["constant"][0]
        self.assertAlmostEqual(actual - value, advantage, places=13)


class ExistingHeadControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(91)
        old_x, current_x = rng.normal(size=(24, 3)), rng.normal(size=(24, 3))
        old_y = (old_x[:, 0] > 0).astype(np.int64)
        current_y = (current_x[:, 1] > 0).astype(np.int64)
        head = NumpyCellHead(3, 2, "gated", seed=7)
        cls.state = CellTrainingState(head, bindings={"test": "synthetic-mathematical-check"},
                                      contexts={"old": dataset_digest(old_x, old_y),
                                                "current": dataset_digest(current_x, current_y)},
                                      active_context="old")
        for _ in range(8):
            cls.state.advance(old_x, old_y)
        cls.state.select_context("current")
        cls.reference = build_reference(cls.state, current_x, current_y,
                                        ((current_x, current_y), (old_x, old_y)), horizon=6)
        cls.target = np.column_stack([np.full(7, -0.03),
                                     cls.reference.observations[0, 1] - cls.reference.observations[:, 1]])

    def test_uncontrolled_nonlinear_path_equals_reference_bitwise(self):
        policy = fit_controller(self.reference, mask="all", mode="zero", target=self.target)
        run = run_nonlinear(self.state, self.reference, policy)
        np.testing.assert_array_equal(run["states"], self.reference.states)
        np.testing.assert_array_equal(run["fields"], np.zeros((7, 2)))
        self.assertEqual(run["physical_intervention_squared_norm"], 0)

    def test_same_policy_transfer_and_bellman_identity(self):
        ref = self.reference
        oracle = fit_controller(ref, mask="all", mode="full", target=self.target)
        for mode in ("zero", "myopic", "loss2", "extended", "full"):
            with self.subTest(mode=mode):
                policy = fit_controller(ref, mask="all", mode=mode, target=self.target)
                result = diagnose_tangent(ref, policy, oracle=oracle)
                self.assertLess(result["bellman_identity_abs_error"], 1e-10)
                self.assertLessEqual(result["transfer_bound_max_violation"], 1e-10)
                self.assertLessEqual(abs(result["same_policy_cost_difference"]),
                                     result["same_policy_cost_bound"] + 1e-12)
                self.assertGreaterEqual(result["combined_information_policy_gap"], -1e-10)
                run = run_nonlinear(self.state, ref, policy)
                self.assertTrue(np.isfinite(run["cost"]["total"]))

    def test_nested_oracle_order_and_actual_parameter_mask(self):
        ref = self.reference
        bias = fit_controller(ref, mask="bias", mode="full", target=self.target)
        complete = fit_controller(ref, mask="all", mode="full", target=self.target)
        self.assertGreaterEqual(bias.riccati["constant"][0] + 1e-12,
                                complete.riccati["constant"][0])
        run = run_nonlinear(self.state, ref, bias)
        parameter_mask = np.any(bias.B != 0, axis=1)
        for k in range(ref.horizon):
            plain = self.state.transition_vector(run["states"][k], self.state.step_count + k,
                                                 ref.train_features, ref.train_labels)
            delta = run["states"][k + 1, :self.state.parameter_count] - plain[:self.state.parameter_count]
            np.testing.assert_array_equal(delta[~parameter_mask], np.zeros((~parameter_mask).sum()))

    def test_analytic_moment_derivatives_match_feasible_direction(self):
        ref, state = self.reference, self.state
        rng = np.random.default_rng(43)
        p, x = state.parameter_count, ref.states[0]
        direction = np.zeros(3 * p)
        direction[p:2 * p] = rng.normal(size=p)
        direction[2 * p:] = rng.normal(size=p)
        direction[2 * p:] *= np.minimum(1, x[2 * p:] / ref.scales[2 * p:])
        eps = 1e-6
        plus = state.transition_vector(x + eps * ref.scales * direction, state.step_count,
                                       ref.train_features, ref.train_labels)
        minus = state.transition_vector(x - eps * ref.scales * direction, state.step_count,
                                        ref.train_features, ref.train_labels)
        numeric = (plus - minus) / (2 * eps) / ref.scales
        np.testing.assert_allclose(ref.A[0] @ direction, numeric, atol=3e-8, rtol=3e-6)


if __name__ == "__main__":
    unittest.main()
