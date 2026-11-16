"""Nonlinear optimizer, sampler, drift, rollback and strict-boundary checks."""

import unittest

import numpy as np

from cell_field_safety_v5 import verify_action
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


class ProspectiveSafetyTests(unittest.TestCase):
    def fixture(self, *, conflict=False, stochastic=False):
        x = np.array([[1., 0.], [-1., 0.], [0., 1.], [0., -1.]])
        y = np.array([0, 1, 0, 1])
        current = 1 - y if conflict else y
        state = CellTrainingState(NumpyCellHead(2, 2, "linear", seed=7),
            bindings={"fixture": "complete-real-head-adam", "seed": 7}, seed=17,
            protocol={"sampler": "iid_with_replacement" if stochastic else "full_batch", "batch_size": 4},
            contexts={"old_train": dataset_digest(x, y), "current_train": dataset_digest(x, current)},
            active_context="old_train")
        for _ in range(32):
            state.advance(x, y)
        state.select_context("current_train")
        baseline = float(state.head.loss_gradients(normalize_features(x), y, 0.0)[0])
        return state, {"current_train": (x, current), "old_probe": (x, y)}, baseline

    def test_certified_sequence_replays_full_rng_clock_moments_and_commit_prefix(self):
        state, data, anchor = self.fixture(stochastic=True)
        original = state.digest()
        actions = np.zeros((8, state.parameter_count))
        actions[:, 0] = 1e-5
        result = verify_action(state, data, actions, anchor, commit_steps=4, action_bound=1.0)
        self.assertTrue(result["record"]["certified"], result["record"])
        manual, receipts, vectors = state.clone(), [], [state.vector()]
        for k in range(8):
            receipts.append(manual.advance(*data["current_train"], intervention=.02 * actions[k]))
            vectors.append(manual.vector())
            if k == 0:
                self.assertEqual(result["next_state"].digest(), manual.digest())
            if k == 3:
                self.assertEqual(result["commit_state"].digest(), manual.digest())
        self.assertEqual((result["state"].digest(), result["receipts"]), (manual.digest(), receipts))
        np.testing.assert_array_equal(result["arrays"]["states"], vectors)
        self.assertEqual(state.digest(), original)
        self.assertEqual(result["state"].sampler_draw_count, state.sampler_draw_count + 32)
        self.assertEqual((result["record"]["certified_optimizer_steps"], result["record"]["committed_optimizer_steps"]), (8, 0))
        self.assertGreater(result["record"]["cpu_ns"], 0)

    def test_safe_first_step_does_not_hide_later_adam_drift_and_zero_is_rejected(self):
        state, data, anchor = self.fixture(conflict=True)
        original, tentative = state.digest(), state.clone()
        tentative.advance(*data["current_train"])
        cancellation = (state.parameter_vector() - tentative.parameter_vector()) / .02
        result = verify_action(state, data, cancellation, anchor, backtracking=(1., 0.))
        self.assertFalse(result["record"]["certified"])
        self.assertLessEqual(result["record"]["attempts"][0]["old_losses"][1], anchor + 1e-15)
        self.assertGreater(max(result["record"]["attempts"][0]["old_losses"][2:]), anchor)
        self.assertEqual([a["status"] for a in result["record"]["attempts"]], ["unsafe", "unsafe"])
        self.assertEqual(result["record"]["verified_optimizer_steps"], 16)
        self.assertEqual(result["record"]["committed_optimizer_steps"], 0)
        self.assertEqual((state.digest(), result["state"].digest()), (original, original))

    def test_backtracking_charges_failed_trials_and_only_accepts_verified_zero(self):
        state, data, anchor = self.fixture()
        _, gradient = state.head.loss_gradients(normalize_features(data["old_probe"][0]), data["old_probe"][1], 0.)
        ascent = np.concatenate([gradient[name].ravel() for name in state.names])
        ascent *= 1000 / np.linalg.norm(ascent)
        result = verify_action(state, data, ascent, anchor, horizon=1)
        self.assertTrue(result["record"]["certified"])
        self.assertEqual(result["record"]["accepted_scale"], 0.)
        self.assertEqual(len(result["record"]["attempts"]), 5)
        self.assertEqual(result["record"]["verified_optimizer_steps"], 5)
        self.assertGreaterEqual(result["record"]["cpu_ns"], sum(a["cpu_ns"] for a in result["record"]["attempts"]))
        self.assertTrue(np.all(result["arrays"]["actions"] == 0))

    def test_rollback_restores_complete_prior_state_without_claiming_a_continuation(self):
        warmup, data, anchor = self.fixture(conflict=True, stochastic=True)
        unsafe = warmup.clone()
        for _ in range(8):
            unsafe.advance(*data["current_train"])
        original = unsafe.digest()
        result = verify_action(unsafe, data, np.zeros(unsafe.parameter_count), anchor, rollback_state=warmup)
        self.assertEqual(result["record"]["status"], "rolled_back")
        self.assertFalse(result["record"]["certified"])
        self.assertFalse(result["record"]["initial_within_threshold"])
        self.assertEqual(result["record"]["committed_optimizer_steps"], 0)
        self.assertEqual(result["state"].digest(), warmup.digest())
        self.assertEqual(result["commit_state"].digest(), warmup.digest())
        self.assertEqual(unsafe.digest(), original)
        incompatible = CellTrainingState(NumpyCellHead(2, 2, "gated", seed=7),
            bindings=warmup.bindings, protocol=warmup.protocol, contexts=warmup.contexts,
            active_context="current_train")
        with self.assertRaisesRegex(ValueError, "compatible complete"):
            verify_action(unsafe, data, np.zeros(unsafe.parameter_count), anchor, rollback_state=incompatible)

    def test_recovery_certificate_reports_initial_violation_separately(self):
        warmup, data, anchor = self.fixture(conflict=True)
        unsafe = warmup.clone()
        for _ in range(8):
            unsafe.advance(*data["current_train"])
        tentative = unsafe.clone()
        tentative.advance(*data["current_train"])
        x, y = data["old_probe"]
        _, gradient = warmup.head.loss_gradients(normalize_features(x), y, 0.)
        desired = warmup.parameter_vector() - .01 * np.concatenate([gradient[n].ravel() for n in warmup.names])
        action = (desired - tentative.parameter_vector()) / .02
        result = verify_action(unsafe, data, action, anchor, horizon=1)
        self.assertTrue(result["record"]["certified"])
        self.assertFalse(result["record"]["initial_within_threshold"])
        self.assertLess(result["arrays"]["old_losses"][1], anchor)

    def test_unavailable_plan_never_becomes_zero_and_invalid_context_budget_reject(self):
        state, data, anchor = self.fixture()
        for status in ("unresolved", "tangent_infeasible"):
            result = verify_action(state, data, None, anchor, candidate_status=status)
            self.assertEqual(result["record"]["status"], "not_executed_" + status)
            self.assertEqual(result["record"]["attempts"], [])
            self.assertEqual(result["state"].digest(), state.digest())
        with self.assertRaises(ValueError):
            verify_action(state, {**data, "old_test": data["old_probe"]}, None, anchor)
        with self.assertRaises(ValueError):
            verify_action(state, data, np.ones(state.parameter_count), anchor, action_bound=.25)
        with self.assertRaises(ValueError):
            verify_action(state, {**data, "current_train": (data["current_train"][0], 1-data["current_train"][1])},
                          np.zeros(state.parameter_count), anchor)

    def test_strict_threshold_has_no_hidden_tolerance_and_nonfinite_rollout_fails_closed(self):
        state, data, _ = self.fixture()
        manual = state.clone()
        manual.advance(*data["current_train"])
        x, y = data["old_probe"]
        boundary = float(manual.head.loss_gradients(normalize_features(x), y, 0.)[0])
        zero = np.zeros(state.parameter_count)
        equal = verify_action(state, data, zero, boundary, horizon=1)
        below = verify_action(state, data, zero, float(np.nextafter(boundary, -np.inf)), horizon=1)
        self.assertTrue(equal["record"]["certified"])
        self.assertFalse(below["record"]["certified"])
        with np.errstate(over="ignore"):
            failed = verify_action(state, data, np.full(state.parameter_count, 1e307), boundary,
                                   horizon=1, backtracking=(1.,))
        self.assertEqual(failed["record"]["status"], "unresolved")
        self.assertEqual(failed["state"].digest(), state.digest())
        self.assertEqual(failed["record"]["committed_optimizer_steps"], 0)


if __name__ == "__main__":
    unittest.main()
