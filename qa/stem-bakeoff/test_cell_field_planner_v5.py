"""Independent convex optima and actual guarded-policy checkpoint/replay checks."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize

from cell_field_planner_v5 import make_plan, solve_terminal
from cell_field_policy_v5 import execute_policy
from cell_field_safety_v5 import verify_action
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def fixture(mode="linear", conflict=False):
    x, y = np.tile(np.eye(8), (4, 1)), np.tile(np.arange(8) % 4, 4)
    current = (y + 1) % 4 if conflict else y
    state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=7), seed=17,
        bindings={"fixture": "planner-guard-integration", "seed": 7, "mode": mode},
        contexts={"old_train": dataset_digest(x, y), "current_train": dataset_digest(x, current)},
        active_context="old_train")
    for step in range(32):
        state.advance(x, y, indices=np.arange(len(y)) if step == 0 else None)
    state.select_context("current_train")
    split = {"old_train": (x, y), "old_probe": (x, y),
             "current_train": (x, current), "current_probe": (x, current)}
    anchor = float(state.head.loss_gradients(normalize_features(x), y, 0.)[0])
    return state, split, anchor


def configuration(steps=16, hard=True, bound=.5):
    return {"steps": steps, "dt": .02, "effort_price": .1, "action_bound": bound,
            "old_weight": .5, "hard_retention": hard, "backtracking": [1., .5, .25, .125, 0.]}


class TerminalPlannerTests(unittest.TestCase):
    def test_scalar_dual_matches_independent_slsqp_with_active_box_and_retention(self):
        rng = np.random.default_rng(442)
        active_dual, active_box = 0, 0
        for horizon, p in ((1, 4), (3, 5), (8, 6)):
            for hard in (False, True):
                rows = rng.normal(0., .05, (horizon, 2, p))
                baseline, dt, rho, price, weight = np.array([1.4, 1.2]), .1, .3, .7, .4
                c, n = (rows[:, 0] + weight * rows[:, 1]).ravel(), rows[:, 1].ravel()
                r, bound = dt * rho, price / np.sqrt(p)
                unconstrained = np.clip(-c / r, -bound, bound)
                minimum = -bound * np.abs(n).sum()
                q = minimum + .35 * (n @ unconstrained - minimum) if hard else -.99
                anchor = float(baseline[1] + q)
                result = solve_terminal(rows, baseline, anchor, dt=dt, effort_price=rho,
                    action_bound=price, old_weight=weight, hard_retention=hard)
                self.assertEqual(result["record"]["status"], "qualified", result["record"])
                objective = lambda u: float(c @ u + .5 * r * (u @ u))
                constraints = [{"type": "ineq", "fun": lambda u: anchor-baseline[1]-n@u,
                                "jac": lambda u: -n}] if hard else []
                independent = minimize(objective, -bound*np.sign(n) if hard else np.zeros_like(c),
                    jac=lambda u: c+r*u, bounds=[(-bound, bound)]*len(c), constraints=constraints,
                    method="SLSQP", options={"ftol": 1e-13, "maxiter": 1000})
                self.assertTrue(independent.success, independent.message)
                actual = result["actions"].ravel()
                np.testing.assert_allclose(actual, independent.x, atol=3e-7, rtol=3e-6)
                self.assertAlmostEqual(objective(actual), objective(independent.x), places=10)
                active_box += int(np.count_nonzero(np.isclose(np.abs(actual), bound)) > 0)
                self.assertLessEqual(result["record"]["stationarity"], 1e-10)
                if hard:
                    active_dual += int(result["record"]["dual_multiplier"] > 0.)
                    self.assertLessEqual(float(n@actual - (anchor-baseline[1])), 1e-12)
                    self.assertLessEqual(result["record"]["gap"], 1e-9)
        self.assertGreater(active_dual, 0)
        self.assertGreater(active_box, 0)

    def test_infeasible_zero_normal_and_exact_single_vertex_feasibility(self):
        rows = np.zeros((2, 2, 4))
        rows[:, 0], rows[:, 1] = .1, 1.
        impossible = solve_terminal(rows, np.array([1., 10.]), 1., action_bound=2.)
        self.assertEqual(impossible["record"]["status"], "tangent_infeasible")
        self.assertIsNone(impossible["actions"])
        self.assertEqual(impossible["record"]["infeasibility_margin"], 1.)
        boundary = solve_terminal(rows, np.array([1., 10.]), 2., action_bound=2.)
        self.assertEqual(boundary["record"]["status"], "qualified")
        np.testing.assert_array_equal(boundary["actions"], -np.ones((2, 4)))
        rows[:, 1] = 0
        impossible = solve_terminal(rows, np.array([1., 2.]), 1.)
        self.assertEqual(impossible["record"]["status"], "tangent_infeasible")
        possible = solve_terminal(rows, np.array([1., 2.]), 2.)
        self.assertEqual(possible["record"]["status"], "qualified")
        self.assertEqual(possible["record"]["dual_multiplier"], 0.)

    def test_finite_scalar_arithmetic_underflow_cannot_qualify_nan_actions(self):
        with np.errstate(all="ignore"):
            try:
                result = solve_terminal(np.zeros((1, 2, 1)), np.zeros(2), 0.,
                    dt=1e-308, effort_price=1e-308, hard_retention=False)
            except ValueError:
                return
        self.assertNotEqual(result["record"]["status"], "qualified")
        self.assertIsNone(result["actions"])

    def test_h1_loss_projection_and_full_response_have_identical_plans(self):
        for mode in ("linear", "gated"):
            state, split, anchor = fixture(mode)
            before = state.digest()
            plans = [make_plan(state, split, anchor, method=method, horizon=1) for method in ("adjoint", "loss2")]
            self.assertEqual([p["record"]["status"] for p in plans], ["qualified", "qualified"])
            np.testing.assert_array_equal(plans[0]["maps"], plans[1]["maps"])
            np.testing.assert_array_equal(plans[0]["actions"], plans[1]["actions"])
            self.assertEqual(state.digest(), before)


class GuardedPolicyTests(unittest.TestCase):
    def check_replay(self, state, split, result, anchor=None):
        replay = state.clone()
        self.assertEqual(result["states"][0].digest(), replay.digest())
        for k, action in enumerate(result["actions"]):
            receipt = replay.advance(*split["current_train"], intervention=.02*action)
            self.assertEqual(receipt, result["receipts"][k])
            self.assertEqual(replay.digest(), result["states"][k+1].digest())
            if anchor is not None:
                loss = replay.head.loss_gradients(normalize_features(split["old_probe"][0]), split["old_probe"][1], 0.)[0]
                self.assertLessEqual(loss, anchor)
        self.assertEqual(replay.digest(), result["state"].digest())

    def test_both_head_guarded_blocks_preserve_complete_metadata_and_saved_checkpoint(self):
        for mode in ("linear", "gated"):
            state, split, anchor = fixture(mode)
            before = state.digest()
            result = execute_policy(state, split, anchor, "response_h8_guarded", configuration())
            self.assertEqual(result["record"]["status"], "completed", result["record"])
            self.assertEqual(result["record"]["completed_steps"], 16)
            self.assertEqual(len(result["states"]), 17)
            self.assertEqual(len(result["plans"]), 2)
            self.check_replay(state, split, result, anchor)
            self.assertEqual(state.digest(), before)
            for record in result["record"]["steps"]:
                self.assertEqual(record["committed_steps"], 8)
                self.assertEqual(record["safety"]["committed_optimizer_steps"], 0)
            self.assertEqual(result["state"].external_batch_count, 1)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "midpoint"
                result["states"][8].save(path)
                restored = CellTrainingState.load(path, state.bindings, state.protocol, state.contexts,
                                                 result["states"][8].digest())
                self.assertEqual(restored.digest(), result["states"][8].digest())

    def test_actual_unsafe_guard_stops_without_substituting_zero_or_resetting_baseline(self):
        state, split, anchor = fixture(conflict=True)
        for _ in range(12):
            state.advance(*split["current_train"])
        before = state.digest()
        result = execute_policy(state, split, anchor, "response_h8_guarded", configuration(8, False, 1e-6))
        self.assertEqual(result["record"]["status"], "not_executed_rejected")
        self.assertEqual(result["record"]["completed_steps"], 0)
        self.assertEqual(result["actions"].shape, (0, state.parameter_count))
        self.assertEqual(result["receipts"], [])
        self.assertEqual(len(result["states"]), 1)
        self.assertEqual((result["state"].digest(), state.digest()), (before, before))
        self.assertEqual(result["record"]["steps"][0]["safety"]["old_anchor"], anchor)
        zero = execute_policy(state, split, anchor, "zero", configuration(8, False, 1e-6))
        self.assertEqual(zero["record"]["completed_steps"], 8)
        self.assertNotEqual(zero["state"].digest(), before)
        self.check_replay(state, split, zero)
        self.assertEqual(state.digest(), before)

    def test_later_numerical_failure_returns_the_complete_already_committed_prefix(self):
        state, split, anchor = fixture()
        calls = 0

        def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("injected later derivative boundary")
            return make_plan(*args, **kwargs)

        before = state.digest()
        with patch("cell_field_policy_v5.make_plan", side_effect=interrupted):
            result = execute_policy(state, split, anchor, "response_h8_guarded", configuration())
        self.assertNotEqual(result["record"]["status"], "completed")
        self.assertEqual(result["record"]["completed_steps"], 8)
        self.assertEqual(len(result["states"]), 9)
        self.assertEqual(result["record"]["steps"][-1]["committed_steps"], 0)
        self.assertIn("injected later derivative boundary", str(result["record"]["steps"][-1]))
        self.check_replay(state, split, result, anchor)
        self.assertEqual(state.digest(), before)

    def test_corrupt_intermediate_checkpoint_cannot_partially_commit_a_guarded_block(self):
        state, split, anchor = fixture()
        before = state.digest()

        def corrupted(*args, **kwargs):
            result = verify_action(*args, **kwargs)
            self.assertTrue(result["record"]["certified"])
            result["arrays"]["states"][3, 0] += 1e-5
            return result

        with patch("cell_field_policy_v5.verify_action", side_effect=corrupted):
            result = execute_policy(state, split, anchor, "response_h8_guarded", configuration(8))
        self.assertNotEqual(result["record"]["status"], "completed")
        self.assertEqual(result["record"]["completed_steps"], 0)
        self.assertEqual(len(result["states"]), 1)
        self.assertEqual(result["receipts"], [])
        self.assertEqual((result["state"].digest(), state.digest()), (before, before))
        self.assertIn("receipt chain", str(result["record"]["steps"][-1]))


if __name__ == "__main__":
    unittest.main()
