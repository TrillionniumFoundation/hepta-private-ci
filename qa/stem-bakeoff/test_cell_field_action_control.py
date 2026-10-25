"""Independent small-QP optima, feasibility witnesses and real-Head impulses."""

import itertools
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_action_control import (action_problem, build_action_model,
    objective_value_gradient, plan_action, score_common, solve_bounded_problem)
from cell_field_control import build_reference
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


def exhaustive_optimum(M, a, N, b, c, constant, regularization, bound, G, q):
    """Enumerate hinge cells and up to n independent active inequalities."""
    n = len(c)
    A, rhs = np.vstack([G, np.eye(n), -np.eye(n)]), np.r_[q, bound, bound]
    answers = []
    for flags in itertools.product((False, True), repeat=len(N)):
        active_hinge = np.array(flags)
        H = M.T @ M + N[active_hinge].T @ N[active_hinge] + regularization * np.eye(n)
        f = M.T @ a + N[active_hinge].T @ b[active_hinge] + c
        for size in range(n + 1):
            for active in itertools.combinations(range(len(rhs)), size):
                C, d = A[list(active)], rhs[list(active)]
                system = np.block([[H, C.T], [C, np.zeros((size, size))]])
                try:
                    solved = np.linalg.solve(system, np.r_[-f, d])
                except np.linalg.LinAlgError:
                    continue
                u, dual = solved[:n], solved[n:]
                old = N @ u + b
                if (np.max(A @ u - rhs) > 1e-10 or np.any(dual < -1e-10)
                        or np.any(old[active_hinge] < -1e-10)
                        or np.any(old[~active_hinge] > 1e-10)):
                    continue
                value = float(constant + c @ u + 0.5 * (np.square(M @ u + a).sum()
                    + np.square(np.maximum(old, 0)).sum() + regularization * (u @ u)))
                answers.append((value, u))
    if not answers:
        raise AssertionError("independent exhaustive problem has no feasible KKT cell")
    return min(answers, key=lambda row: row[0])


class BoundedSolverTests(unittest.TestCase):
    def fixture(self):
        return {"M": np.array([[1.0, 0.4], [-0.2, 0.7]]), "a": np.array([-1.0, 0.5]),
                "N": np.array([[0.5, -1.0], [-0.3, -0.2]]), "b": np.array([0.2, -0.1]),
                "c": np.array([-0.2, 0.12]), "constant": 0.12, "regularization": 0.08,
                "bound": np.array([0.35, 0.6]), "G": np.array([[1.0, 1.0]]), "q": np.array([0.1])}

    def test_optimum_and_dual_gap_match_independent_active_set_enumeration(self):
        problem = self.fixture()
        expected, u = exhaustive_optimum(**problem)
        result = solve_bounded_problem(**problem)
        self.assertTrue(result["record"]["qualified"], result["record"])
        np.testing.assert_allclose(result["u"], u, atol=2e-7, rtol=2e-7)
        self.assertAlmostEqual(result["record"]["objective"], expected, places=11)
        dual, A, rhs = result["dual"], result["certificate_A"], result["certificate_b"]
        stationarity = result["gradient"] + A.T @ dual
        lower = result["record"]["objective"] + dual @ (A @ result["u"] - rhs)
        lower -= stationarity @ stationarity / (2 * problem["regularization"])
        relaxed = dict(problem, q=problem["q"] + 1e-9)
        relaxed_optimum = exhaustive_optimum(**relaxed)[0]
        self.assertLessEqual(lower, relaxed_optimum + 5e-14)
        self.assertLessEqual(relaxed_optimum, result["record"]["objective"] + 5e-14)
        self.assertGreaterEqual(dual.min(), 0.0)

    def test_box_farkas_witness_is_positive_for_every_box_corner(self):
        problem = self.fixture()
        problem.update(G=np.array([[1.0, 0.0], [-1.0, 0.0]]), q=np.array([-0.2, -0.2]))
        result = solve_bounded_problem(**problem)
        self.assertEqual(result["record"]["status"], "tangent_infeasible_with_box_witness")
        self.assertEqual(len(result["u"]), 0)
        mu = result["farkas_weights"]
        self.assertTrue(np.all(mu >= 0))
        self.assertAlmostEqual(mu.sum(), 1.0, places=13)
        values = [float(mu @ (problem["G"] @ (np.array(signs) * problem["bound"])
                              - problem["q"] - 1e-9))
                  for signs in itertools.product((-1.0, 1.0), repeat=2)]
        margin = result["record"]["phase_one"]["witness_margin"]
        self.assertGreater(margin, 1e-9)
        self.assertAlmostEqual(min(values), margin, places=13)

    def test_phase_one_finds_nonzero_feasible_start_and_solver_failure_is_retained(self):
        problem = self.fixture()
        problem.update(G=np.array([[1.0, 1.0]]), q=np.array([-0.3]))
        result = solve_bounded_problem(**problem)
        self.assertEqual(result["record"]["phase_one"]["status"], "phase_one_feasible")
        self.assertTrue(result["record"]["qualified"], result["record"])
        self.assertLessEqual(np.max(problem["G"] @ result["u"] - problem["q"]), 1e-9)
        failed = solve_bounded_problem(**self.fixture(), max_iterations=1, gap_tolerance=1e-16)
        self.assertFalse(failed["record"]["qualified"])
        self.assertEqual(failed["record"]["status"], "solver_failed_or_unresolved")
        self.assertNotEqual(len(failed["u"]), 0)

    def test_exact_gradient_and_invalid_inputs(self):
        problem, u = self.fixture(), np.array([0.13, -0.21])
        objective = {k: problem[k] for k in ("M", "a", "N", "b", "c", "constant", "regularization")}
        analytic = objective_value_gradient(**objective, u=u)[1]
        finite = [(objective_value_gradient(**objective, u=u + 1e-6 * np.eye(2)[j])[0]
                   - objective_value_gradient(**objective, u=u - 1e-6 * np.eye(2)[j])[0]) / 2e-6
                  for j in range(2)]
        np.testing.assert_allclose(analytic, finite, atol=1e-9, rtol=1e-9)
        for change in ({"bound": np.zeros(2)}, {"regularization": 0.0},
                       {"G": np.ones((1, 3))}, {"c": np.array([np.nan, 0.0])}):
            with self.assertRaises(ValueError):
                solve_bounded_problem(**dict(problem, **change))

    def test_nonfinite_solver_proposal_is_preserved_without_executable_actions(self):
        failed = SimpleNamespace(x=np.array([np.inf, 0.0]), success=False, status=8,
                                 message="synthetic nonfinite solver proposal", nit=1)
        model = {"loss_maps": np.zeros((9, 2, 2)), "reference_observations": np.zeros((9, 2))}
        with patch("cell_field_action_control.minimize", return_value=failed):
            result = plan_action(model, objective="direct_soft", lookahead=8, old_anchor=1.0)
        self.assertEqual(result["status"], "solver_failed_or_unresolved")
        self.assertFalse(result["record"]["qualified"])
        self.assertEqual(result["record"]["failure"], "invalid_or_nonfinite_solver_proposal")
        self.assertTrue(np.isinf(result["u"][0]))
        self.assertEqual(result["actions"].size, 0)
        self.assertEqual(result["fields"].size, 0)
        json.dumps(result["record"], allow_nan=False)


class OneActionHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(291)
        old_x, current_x = rng.normal(size=(24, 3)), rng.normal(size=(24, 3))
        old_y, current_y = (old_x[:, 0] > 0).astype(int), (current_x[:, 1] > 0).astype(int)
        cls.state = CellTrainingState(NumpyCellHead(3, 2, "gated", seed=7),
            bindings={"test": "one-action-synthetic-no-final-labels"},
            contexts={"old": dataset_digest(old_x, old_y), "current": dataset_digest(current_x, current_y)},
            active_context="old")
        for _ in range(12):
            cls.state.advance(old_x, old_y)
        cls.state.select_context("current")
        cls.ref = build_reference(cls.state, current_x, current_y,
                                  ((current_x, current_y), (old_x, old_y)), horizon=8)
        cls.models = {name: build_action_model(cls.ref, observation=name) for name in ("loss2", "full")}

    def test_direct_objective_matches_tracking_gradient_at_zero_for_all_lookaheads(self):
        for model in self.models.values():
            for lookahead in (1, 4, 8):
                a = action_problem(model, objective="tracking_soft", lookahead=lookahead, old_anchor=1.0)
                b = action_problem(model, objective="direct_soft", lookahead=lookahead, old_anchor=1.0)
                zero = np.zeros(len(a["c"]))
                ga, gb = [objective_value_gradient(**{k: p[k] for k in
                    ("M", "a", "N", "b", "c", "constant", "regularization")}, u=zero)[1]
                          for p in (a, b)]
                np.testing.assert_allclose(ga, gb, atol=1e-17, rtol=1e-13)
                np.testing.assert_array_equal(a["N"], b["N"])
                np.testing.assert_array_equal(a["b"], b["b"])

    def test_hard_constraints_are_common_full_horizon_and_only_add_constraints(self):
        for model in self.models.values():
            Gs, qs = [], []
            for lookahead in (1, 4, 8):
                soft = action_problem(model, objective="direct_soft", lookahead=lookahead, old_anchor=1.0)
                hard = action_problem(model, objective="direct_hard", lookahead=lookahead, old_anchor=1.0)
                for key in ("M", "a", "N", "b", "c", "bound"):
                    np.testing.assert_array_equal(soft[key], hard[key])
                self.assertEqual(hard["G"].shape[0], 8)
                Gs.append(hard["G"])
                qs.append(hard["q"])
            for G, q in zip(Gs[1:], qs[1:]):
                np.testing.assert_array_equal(G, Gs[0])
                np.testing.assert_array_equal(q, qs[0])

    def test_same_one_action_full_tangent_matches_manual_propagation_and_zero_replay(self):
        model = self.models["full"]
        u = np.linspace(-0.02, 0.02, self.state.parameter_count)
        z = np.zeros_like(self.ref.states)
        z[1] = model["E"][0] @ u
        for k in range(1, 8):
            z[k + 1] = self.ref.A[k] @ z[k]
        manual = np.einsum("kij,kj->ki", self.ref.C[:, :2], z)
        mapped = np.einsum("kij,j->ki", model["loss_maps"], u)
        np.testing.assert_allclose(mapped, manual, atol=2e-17, rtol=2e-14)
        state, path = self.state.clone(), [self.state.vector()]
        for _ in range(8):
            state.advance(self.ref.train_features, self.ref.train_labels)
            path.append(state.vector())
        np.testing.assert_array_equal(np.asarray(path), self.ref.states)

    def test_all_objectives_have_bounded_deterministic_first_action_and_common_scores(self):
        anchor = float(self.ref.observations[:, 1].max() + 1.0)
        for model in self.models.values():
            for objective in ("tracking_soft", "direct_soft", "direct_hard"):
                plan = plan_action(model, objective=objective, lookahead=8, old_anchor=anchor)
                self.assertEqual(plan["status"], "qualified", plan["record"])
                self.assertTrue(np.all(plan["actions"][1:] == 0))
                self.assertLessEqual(np.linalg.norm(0.02 * plan["u"]), 0.02 + 1e-15)
                common = score_common(plan["fields"], plan["actions"],
                                      model["reference_observations"], anchor)
                key = "tracking_soft_total" if objective == "tracking_soft" else "direct_soft_total"
                self.assertAlmostEqual(common[key], plan["record"]["objective"], places=13)
                again = plan_action({k: v.copy() for k, v in model.items()},
                                    objective=objective, lookahead=8, old_anchor=anchor)
                np.testing.assert_array_equal(plan["u"], again["u"])
                np.testing.assert_array_equal(plan["dual"], again["dual"])


if __name__ == "__main__":
    unittest.main()
