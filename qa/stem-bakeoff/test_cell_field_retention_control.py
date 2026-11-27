"""Independent active-set checks and real-Head retention-control integration."""

import itertools
import unittest

import numpy as np

from cell_field_control import build_reference, fit_controller, run_nonlinear, solve_lq
from cell_field_retention_control import (
    RetentionController, condense_dynamics, condensed_value_gradient,
    diagnose_retention_tangent, fit_retention_controller, initial_optimum,
    retention_cost, run_retention_nonlinear, solve_squared_hinge)
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class HingeSolverTests(unittest.TestCase):
    def test_improving_old_loss_is_not_penalized(self):
        fields = np.array([[0.0, -0.1], [0.0, -0.2]])
        result = retention_cost(fields, np.zeros((1, 1)), np.zeros((2, 2)), 0.02, 0.1)
        self.assertEqual(result["total"], 0.0)
        self.assertEqual(result["old_violation_steps"], 0)
        fields[-1, 1] = 0.1
        result = retention_cost(fields, np.zeros((1, 1)), np.zeros((2, 2)), 0.02, 0.1)
        self.assertAlmostEqual(result["forgetting"], 0.005)
        self.assertEqual(result["old_violation_steps"], 1)

    def test_convex_solver_matches_exhaustive_independent_active_sets(self):
        rng = np.random.default_rng(2041)
        M, N = rng.normal(size=(4, 3)), rng.normal(size=(4, 3))
        a, b, price = rng.normal(size=4), rng.normal(size=4), 0.2
        candidates = []
        for flags in itertools.product((False, True), repeat=4):
            active = np.array(flags)
            H = M.T @ M + N[active].T @ N[active] + price * np.eye(3)
            rhs = M.T @ a + N[active].T @ b[active]
            u = np.linalg.solve(H, -rhs)
            old = N @ u + b
            if np.all(old[active] >= -1e-12) and np.all(old[~active] <= 1e-12):
                value = 0.5 * (np.square(M @ u + a).sum()
                               + np.square(np.maximum(old, 0)).sum() + price * (u @ u))
                candidates.append((value, u))
        self.assertTrue(candidates)
        expected = min(candidates, key=lambda row: row[0])
        result = solve_squared_hinge(M, a, N, b, price)
        self.assertTrue(result["record"]["converged"])
        self.assertAlmostEqual(result["record"]["objective"], expected[0], places=11)
        np.testing.assert_allclose(result["controls"], expected[1], atol=1e-9, rtol=1e-9)
        gap = result["record"]["objective"] - expected[0]
        self.assertLessEqual(gap, result["record"]["optimality_gap_bound"] + 1e-12)
        self.assertTrue(np.all(np.diff(result["history"][:, 0]) <= 1e-12))

    def test_gradient_matches_finite_difference_and_budget_failure_is_retained(self):
        rng = np.random.default_rng(133)
        M, N = rng.normal(size=(5, 3)), rng.normal(size=(5, 3))
        a, b, u = rng.normal(size=5), rng.normal(size=5), rng.normal(size=3)
        analytic = condensed_value_gradient(M, a, N, b, 0.3, u)[1]
        numeric = []
        for j in range(3):
            delta = np.eye(3)[j] * 1e-6
            numeric.append((condensed_value_gradient(M, a, N, b, 0.3, u + delta)[0]
                            - condensed_value_gradient(M, a, N, b, 0.3, u - delta)[0]) / 2e-6)
        np.testing.assert_allclose(analytic, numeric, atol=2e-8, rtol=2e-8)
        failed = solve_squared_hinge(np.ones((1, 1)), np.array([-2.0]),
                                    np.ones((1, 1)), np.zeros(1), 0.1, max_iterations=1)
        self.assertFalse(failed["record"]["converged"])
        self.assertEqual(failed["record"]["failure"], "iteration_budget_exhausted")
        self.assertGreater(failed["record"]["optimality_gap_bound"], 1e-10)

    def test_symmetric_condensed_plans_equal_riccati_at_arbitrary_remaining_states(self):
        rng = np.random.default_rng(740)
        horizon, dim, act, dt, price = 6, 3, 2, 0.02, 0.1
        F = np.array([0.8 * np.eye(dim) + rng.normal(0, 0.04, (dim, dim))
                      for _ in range(horizon)])
        D = rng.normal(0, 0.1, (horizon, dim, act))
        C = rng.normal(0, 0.2, (horizon + 1, 2, dim))
        target = rng.normal(0, 0.1, (horizon + 1, 2))
        riccati = solve_lq(F, D, C, target, dt, price)
        for k in range(horizon):
            x = rng.normal(size=dim)
            maps = condense_dynamics(F, D, C, target, dt, k)
            a = maps["current_state"] @ x + maps["current_offset"]
            b = maps["old_state"] @ x + maps["old_offset"]
            solved = solve_squared_hinge(maps["M"], a, maps["N"], b,
                                         dt * price, one_sided=False)
            observed, state = [], x.copy()
            for step in range(k, horizon):
                action = -riccati["K"][step] @ state + riccati["offset"][step]
                observed.append(action)
                state = F[step] @ state + D[step] @ action
            np.testing.assert_allclose(solved["controls"], np.asarray(observed).ravel(),
                                       atol=2e-11, rtol=2e-11)
            expected_value = (0.5 * x @ riccati["P"][k] @ x
                              + riccati["ell"][k] @ x + riccati["constant"][k])
            self.assertAlmostEqual(solved["record"]["objective"], expected_value, places=12)


class RetentionHeadIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(19)
        old_x, current_x = rng.normal(size=(24, 3)), rng.normal(size=(24, 3))
        old_y, current_y = (old_x[:, 0] > 0).astype(int), (current_x[:, 1] > 0).astype(int)
        cls.state = CellTrainingState(NumpyCellHead(3, 2, "gated", seed=7),
            bindings={"test": "synthetic-no-holdout"},
            contexts={"old": dataset_digest(old_x, old_y),
                      "current": dataset_digest(current_x, current_y)}, active_context="old")
        for _ in range(8):
            cls.state.advance(old_x, old_y)
        cls.state.select_context("current")
        cls.ref = build_reference(cls.state, current_x, current_y,
                                   ((current_x, current_y), (old_x, old_y)), horizon=6)
        cls.target = np.column_stack([np.full(7, -0.03),
                                      cls.ref.observations[0, 1] - cls.ref.observations[:, 1]])

    def controller(self, mode, mask="all"):
        return fit_retention_controller(self.ref, mode=mode, mask=mask, target=self.target)

    def test_zero_reference_and_symmetric_ablation_match_original_paths_bitwise(self):
        zero = run_retention_nonlinear(self.state, self.ref, self.controller("zero"))
        np.testing.assert_array_equal(zero["states"], self.ref.states)
        legacy = fit_controller(self.ref, mask="all", mode="loss2", target=self.target)
        old = run_nonlinear(self.state, self.ref, legacy)
        new = run_retention_nonlinear(self.state, self.ref, self.controller("symmetric_loss2"))
        np.testing.assert_array_equal(new["states"], old["states"])
        np.testing.assert_array_equal(new["actions"], old["actions"])
        self.assertEqual(new["legacy_symmetric_cost"], old["cost"])

    def test_roundtrip_has_no_hidden_solver_state_and_records_all_feedback(self):
        controller = self.controller("loss2")
        run = run_retention_nonlinear(self.state, self.ref, controller)
        reopened = RetentionController.from_arrays(controller.arrays(), mode="loss2",
                                                    mask="all", dt=self.ref.dt)
        for k in range(6):
            observation = run["observations"][k, :2] - self.ref.observations[k, :2]
            np.testing.assert_array_equal(controller.action(k, observation),
                                          reopened.action(k, observation))
        self.assertEqual(len(run["solver_records"]), 6)
        self.assertTrue(all(row["converged"] for row in run["solver_records"]))
        np.testing.assert_array_equal(run["planned_actions"][:, 0], run["actions"])
        np.testing.assert_array_equal(run["plan_lengths"], np.arange(6, 0, -1))

    def test_nested_oracles_and_retention_tangent_gap(self):
        bias, full = self.controller("full", "bias"), self.controller("full")
        small, large = initial_optimum(bias), initial_optimum(full)
        self.assertLessEqual(large["value_lower"], small["value_upper"] + 1e-12)
        for mode in ("myopic", "loss2", "extended", "full", "symmetric_loss2"):
            controller = self.controller(mode)
            result = diagnose_retention_tangent(self.ref, controller, oracle=full)
            self.assertGreaterEqual(result["combined_information_policy_gap_interval"][1], -1e-10)
            self.assertEqual(len(result["solver_records"]), 6)
        run = run_retention_nonlinear(self.state, self.ref, bias)
        mask = np.any(bias.B != 0, axis=1)
        for k in range(6):
            plain = self.state.transition_vector(run["states"][k], self.state.step_count + k,
                                                 self.ref.train_features, self.ref.train_labels)
            difference = run["states"][k + 1, :self.state.parameter_count] - plain[:self.state.parameter_count]
            np.testing.assert_array_equal(difference[~mask], np.zeros(np.count_nonzero(~mask)))


if __name__ == "__main__":
    unittest.main()
