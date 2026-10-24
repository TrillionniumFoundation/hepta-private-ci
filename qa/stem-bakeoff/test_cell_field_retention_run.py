"""Actual-head transition, unchanged-baseline and failure/replay tests, not efficacy."""

import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_control import build_reference, fit_controller, run_nonlinear
from cell_field_retention import RetentionSolveError, solve_retention_tangent
from cell_field_retention_run import (ARMS, RetentionRunError, RetentionRunLimits,
                                      run_retention_control)
from cell_field_retention_checkpoint import load_retention_pause, save_retention_run
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


class RetentionDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(341)
        old_x, current_x = rng.normal(size=(24, 3)), rng.normal(size=(24, 3))
        old_y = (old_x[:, 0] > 0).astype(np.int64)
        current_y = (current_x[:, 1] > 0).astype(np.int64)
        state = CellTrainingState(NumpyCellHead(3, 2, "gated", seed=7),
            bindings={"scope": "local mathematical actual-head test; no empirical claim"},
            contexts={"old": dataset_digest(old_x, old_y),
                      "current": dataset_digest(current_x, current_y)}, active_context="old")
        for _ in range(8):
            state.advance(old_x, old_y)
        state.select_context("current")
        cls.state = state
        cls.ref = build_reference(state, current_x, current_y,
                                  ((current_x, current_y), (old_x, old_y)), horizon=5)
        cls.anchor = float(cls.ref.observations[0, 1])
        cls.kwargs = {"anchor": cls.anchor, "tolerance": 0.02,
                      "current_target": -0.03, "effort_price": 0.1}

    def run_arm(self, arm, **kwargs):
        return run_retention_control(self.state, self.ref, arm=arm, **{**self.kwargs, **kwargs})

    def test_zero_arm_equals_original_reference_and_legacy_runner_bitwise(self):
        result = self.run_arm("zero")
        policy = fit_controller(self.ref, mask="bias", mode="zero",
                                target=result["legacy_target"], effort_price=0.1)
        legacy = run_nonlinear(self.state, self.ref, policy)
        np.testing.assert_array_equal(result["states"], self.ref.states)
        for name in ("states", "observations", "actions", "fields"):
            np.testing.assert_array_equal(result[name], legacy[name])
        self.assertEqual(result["costs"]["legacy_quadratic"], legacy["cost"])
        self.assertEqual(result["receipt"]["status"], "completed")

    def test_quadratic_arm_keeps_original_fit_action_target_and_cost(self):
        for mask in ("bias", "all"):
            with self.subTest(mask=mask):
                result = self.run_arm("legacy_full_quadratic", mask=mask)
                policy = fit_controller(self.ref, mask=mask, mode="full",
                                        target=result["legacy_target"], effort_price=0.1)
                legacy = run_nonlinear(self.state, self.ref, policy)
                for name in ("states", "observations", "actions", "fields"):
                    np.testing.assert_array_equal(result[name], legacy[name])
                self.assertEqual(result["costs"]["legacy_quadratic"], legacy["cost"])
                np.testing.assert_array_equal(result["legacy_target"][:, 1],
                                              self.anchor - self.ref.observations[:, 1])

    def test_suffix_matches_independent_actual_state_loop_with_fixed_anchor(self):
        result = self.run_arm("retention_hinge_suffix")
        state, ref = self.state.clone(), self.ref
        B, E = ref.action_matrix("bias")
        original_anchor_targets = self.anchor + 0.02 - ref.observations[:, 1]
        np.testing.assert_array_equal(result["target"][:, 1], original_anchor_targets)
        expected_actions, expected_states = [], [state.vector()]
        for k in range(ref.horizon):
            solution = solve_retention_tangent(ref.A[k:], E[k:], ref.C[k:, :2],
                result["target"][k:], ref.dt, 0.1,
                initial=(state.vector() - ref.states[k]) / ref.scales)
            action = solution["actions"][0]
            expected_actions.append(action)
            state.advance(ref.train_features, ref.train_labels,
                          intervention=ref.dt * B @ action, mask=np.any(B != 0, axis=1))
            expected_states.append(state.vector())
        np.testing.assert_array_equal(result["actions"], expected_actions)
        np.testing.assert_array_equal(result["states"], expected_states)
        self.assertEqual(result["state"].digest(), state.digest())
        self.assertGreater(max(d["scaled_one_step_prediction_error_l2"]
                               for d in result["receipt"]["decisions"]), 0)

    def test_physical_dt_once_and_declared_parameter_mask(self):
        result = self.run_arm("retention_hinge_suffix")
        ref, p = self.ref, self.state.parameter_count
        B, _ = ref.action_matrix("bias")
        for k, action in enumerate(result["actions"]):
            plain = self.state.transition_vector(result["states"][k], self.state.step_count + k,
                                                  ref.train_features, ref.train_labels)
            np.testing.assert_array_equal(result["states"][k + 1, p:], plain[p:])
            expected = plain.copy()
            expected[:p] += ref.dt * B @ action
            np.testing.assert_array_equal(result["states"][k + 1], expected)
        self.assertEqual(result["state"].step_count, self.state.step_count + ref.horizon)
        self.assertEqual(result["state"].sampler_draw_count, self.state.sampler_draw_count)

    def test_pause_replay_suffix_is_bitwise_identical_for_all_arms(self):
        before, reference_before = self.state.digest(), self.ref.states.copy()
        for arm in ARMS:
            with self.subTest(arm=arm):
                full = self.run_arm(arm)
                partial = self.run_arm(arm, stop_after=2)
                self.assertEqual(partial["receipt"]["status"], "paused")
                self.assertIsNone(partial["costs"])
                recovered = self.run_arm(arm, resume=partial)
                for name in ("states", "observations", "actions", "fields"):
                    np.testing.assert_array_equal(full[name], recovered[name])
                self.assertEqual(full["state"].digest(), recovered["state"].digest())
                self.assertEqual(recovered["receipt"]["recovery"]["replayed_steps"], 2)
                self.assertEqual(recovered["receipt"]["phase_costs"]["recovery_transition"]["calls"], 2)
                self.assertEqual(full["costs"], recovered["costs"])
        self.assertEqual(self.state.digest(), before)
        np.testing.assert_array_equal(self.ref.states, reference_before)

    def test_drifting_anchor_or_wrong_initial_state_reject_before_transition(self):
        for anchor in (self.anchor + 0.001, True, float("nan")):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                self.run_arm("retention_hinge_suffix", anchor=anchor)
        other = self.state.clone()
        other.advance(self.ref.train_features, self.ref.train_labels)
        with self.assertRaisesRegex(ValueError, "identity"):
            run_retention_control(other, self.ref, arm="zero", **self.kwargs)

    def test_bad_training_context_reference_or_limits_reject(self):
        changed = copy.deepcopy(self.ref)
        changed.train_features[0, 0] += 0.1
        with self.assertRaisesRegex(ValueError, "context"):
            run_retention_control(self.state, changed, arm="zero", **self.kwargs)
        for limits in (replace(RetentionRunLimits(), max_action_l2=float("inf")),
                       replace(RetentionRunLimits(), max_solver_iterations=True)):
            with self.assertRaises(ValueError):
                self.run_arm("zero", limits=limits)
        changed = copy.deepcopy(self.ref)
        changed.observations[-1, 1] += 0.0001
        with self.assertRaisesRegex(ValueError, "replay"):
            run_retention_control(self.state, changed, arm="zero", **self.kwargs)

    def test_changed_resume_contract_rejects_and_retains_failure(self):
        partial = self.run_arm("retention_hinge_suffix", stop_after=2)
        with self.assertRaises(RetentionRunError) as caught:
            self.run_arm("retention_hinge_suffix", tolerance=0.03, resume=partial)
        result = caught.exception.result
        self.assertEqual(result["receipt"]["failure_stage"], "recovery_verification")
        self.assertEqual(result["receipt"]["applied_steps"], 0)
        self.assertIsNone(result["costs"])

    def test_tampered_paused_action_cannot_silently_resume(self):
        partial = self.run_arm("retention_hinge_suffix", stop_after=2)
        partial["actions"][0, 0] += 0.0001
        with self.assertRaises(RetentionRunError) as caught:
            self.run_arm("retention_hinge_suffix", resume=partial)
        result = caught.exception.result
        self.assertIn("replay", result["receipt"]["error"]["message"])
        self.assertEqual(result["receipt"]["applied_steps"], 1)
        self.assertEqual(result["state"].digest(), result["steps"][-1]["state_sha256"])

    def test_guard_rejection_preserves_spent_solver_work_without_clipping(self):
        limits = replace(RetentionRunLimits(), max_action_l2=1e-12)
        with self.assertRaises(RetentionRunError) as caught:
            self.run_arm("retention_hinge_suffix", limits=limits)
        result = caught.exception.result
        self.assertEqual(result["receipt"]["applied_steps"], 0)
        self.assertFalse(result["receipt"]["decisions"][0]["applied"])
        self.assertEqual(len(result["receipt"]["solver_receipts"]), 1)
        self.assertGreater(result["receipt"]["phase_costs"]["suffix_solve"]["cpu_ns"], 0)
        self.assertEqual(result["state"].digest(), self.state.digest())
        canonical(result["receipt"])

    def test_post_effect_guard_failure_keeps_actual_state_and_applied_step(self):
        limits = replace(RetentionRunLimits(), max_scaled_displacement_l2=1e-12)
        with self.assertRaises(RetentionRunError) as caught:
            self.run_arm("retention_hinge_suffix", limits=limits)
        result = caught.exception.result
        self.assertEqual(result["receipt"]["applied_steps"], 1)
        self.assertEqual(len(result["states"]), 2)
        self.assertEqual(result["receipt"]["observed_states"], 1)
        self.assertTrue(result["receipt"]["decisions"][0]["applied"])
        self.assertEqual(result["state"].digest(), result["steps"][-1]["state_sha256"])
        self.assertIsNone(result["costs"])
        canonical(result["receipt"])

    def test_cooperative_budget_failure_is_not_reported_as_completion(self):
        limits = replace(RetentionRunLimits(), max_cpu_seconds=1e-20)
        with self.assertRaises(RetentionRunError) as caught:
            self.run_arm("zero", limits=limits)
        receipt = caught.exception.result["receipt"]
        self.assertEqual(receipt["status"], "failed")
        self.assertGreater(receipt["cpu_ns"], 0)
        self.assertEqual(receipt["applied_steps"], 0)

    def test_solver_failure_keeps_its_attempt_receipt_without_legacy_fallback(self):
        failure = RetentionSolveError("deliberate numerical failure", {
            "converged": False, "failure_stage": "iteration_budget", "riccati_solve_attempts": 3})
        with patch("cell_field_retention_run.solve_retention_tangent", side_effect=failure):
            with self.assertRaises(RetentionRunError) as caught:
                self.run_arm("retention_hinge_suffix")
        result = caught.exception.result
        self.assertEqual(result["receipt"]["solver_receipts"][0]["riccati_solve_attempts"], 3)
        self.assertEqual(result["receipt"]["applied_steps"], 0)
        self.assertNotIn("legacy_policy_build", result["receipt"]["phase_costs"])

    def test_legacy_numerical_failure_is_retained_under_same_census_rule(self):
        with patch("cell_field_retention_run.fit_controller", side_effect=np.linalg.LinAlgError("deliberate")):
            with self.assertRaises(RetentionRunError) as caught:
                self.run_arm("legacy_full_quadratic")
        result = caught.exception.result
        self.assertEqual(result["receipt"]["failure_stage"], "legacy_policy_build")
        self.assertEqual(result["receipt"]["phase_costs"]["legacy_policy_build"]["calls"], 1)
        self.assertEqual(result["receipt"]["applied_steps"], 0)

    def test_probe_failure_after_effect_retains_effect_without_scoring_partial_path(self):
        ref = copy.deepcopy(self.ref)
        real_observe, calls = ref.observe, []

        def observe(value):
            calls.append(1)
            if len(calls) == self.ref.horizon + 3:
                raise ValueError("deliberate post-transition observation failure")
            return real_observe(value)

        ref.observe = observe
        with self.assertRaises(RetentionRunError) as caught:
            run_retention_control(self.state, ref, arm="zero", **self.kwargs)
        result = caught.exception.result
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(len(result["states"]), 2)
        self.assertEqual(result["state"].digest(), result["steps"][-1]["state_sha256"])
        self.assertEqual(result["receipt"]["phase_costs"]["actual_probe_observation"]["calls"], 2)
        self.assertIsNone(result["costs"])

    def test_persist_restore_replay_keeps_full_optimizer_and_frozen_contract(self):
        partial = self.run_arm("retention_hinge_suffix", stop_after=2)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "checkpoint"
            saved = save_retention_run(target, partial)
            restored = load_retention_pause(target, self.state)
            self.assertEqual(restored["state"].digest(), partial["state"].digest())
            self.assertEqual(restored["checkpoint_cost"]["write_manifest"], saved)
            resumed = self.run_arm("retention_hinge_suffix", resume=restored)
            full = self.run_arm("retention_hinge_suffix")
            np.testing.assert_array_equal(resumed["states"], full["states"])
            with self.assertRaises(FileExistsError):
                save_retention_run(target, partial)
            payload = target / "trajectory.npz"
            payload.write_bytes(payload.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_retention_pause(target, self.state)

    def test_failed_and_unfinished_checkpoints_cannot_load_as_paused(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "completed"
            save_retention_run(target, self.run_arm("zero"))
            with self.assertRaisesRegex(ValueError, "paused"):
                load_retention_pause(target, self.state)
            (target / "manifest.json").unlink()
            with self.assertRaises(ValueError):
                load_retention_pause(target, self.state)


if __name__ == "__main__":
    unittest.main()
