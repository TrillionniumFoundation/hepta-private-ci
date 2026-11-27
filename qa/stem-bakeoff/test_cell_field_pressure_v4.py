"""Original-threshold pressure, full-state replay and failed-candidate preservation."""

import copy
from types import SimpleNamespace
import unittest

import numpy as np

from cell_field_action_control import build_action_model
from cell_field_control import build_reference
from cell_field_pressure_v4 import execute_pressure, plan_pressure, search_pressure
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.default_rng(51).normal(size=(24, 2))
        self.y = (self.x[:, 0] > 0).astype(int)
        self.current_y = 1 - self.y
        self.state = CellTrainingState(NumpyCellHead(2, 2, "linear", seed=7),
            bindings={"fixture": "synthetic-original-threshold"},
            contexts={"old_train": dataset_digest(self.x, self.y),
                      "current_train": dataset_digest(self.x, self.current_y)}, active_context="old_train")
        for _ in range(32):
            self.state.advance(self.x, self.y)
        self.development = {"current_train": (self.x, self.current_y), "old_probe": (self.x, self.y)}

    def test_first_crossing_and_prevention_recovery_keep_full_optimizer_state(self):
        original = self.state.digest()
        result = search_pressure(self.state, self.development, max_steps=64, horizon=3)
        record = result["record"]
        self.assertEqual(record["status"], "pressure_crossing")
        self.assertEqual(self.state.digest(), original)
        manual, states = self.state.clone(), []
        manual.select_context("current_train")
        states.append(manual.clone())
        losses = [record["old_anchor"]]
        for _ in range(record["tau"]):
            manual.advance(self.x, self.current_y)
            states.append(manual.clone())
            losses.append(manual.head.loss_gradients(normalize_features(self.x), self.y, 0.0)[0])
        self.assertTrue(all(value <= record["old_anchor"] for value in losses[:-1]))
        self.assertGreater(losses[-1], record["old_anchor"])
        for name, offset in record["checkpoint_offsets"].items():
            self.assertEqual(result["checkpoints"][name].digest(), states[offset].digest())
            np.testing.assert_array_equal(result["checkpoints"][name].vector(), states[offset].vector())
        self.assertEqual(record["checkpoint_offsets"]["prevention"], max(0, record["tau"] - 3))
        np.testing.assert_array_equal(result["old_losses"], losses)

    def test_no_pressure_retains_full_bounded_search_without_fake_anchor(self):
        state = CellTrainingState(self.state.head, bindings={"fixture": "no-pressure"},
            contexts={"current_train": dataset_digest(self.x, self.y)}, active_context="current_train")
        for _ in range(2):
            state.advance(self.x, self.y)
        result = search_pressure(state, {"current_train": (self.x, self.y), "old_probe": (self.x, self.y)}, max_steps=4)
        self.assertEqual(result["record"]["status"], "no_pressure_crossing")
        self.assertEqual((result["record"]["tau"], result["checkpoints"]), (None, {}))
        self.assertEqual((result["record"]["completed_steps"], len(result["receipts"]), len(result["states"])), (4, 4, 5))

    def test_withheld_roles_wrong_context_and_unbounded_search_reject(self):
        for extra in ("final", "old_validation", "future_june"):
            with self.assertRaises(ValueError):
                search_pressure(self.state, {**self.development, extra: (self.x, self.y)})
        for limit in (0, 257, True):
            with self.assertRaises(ValueError):
                search_pressure(self.state, self.development, max_steps=limit)
        with self.assertRaises(ValueError):
            search_pressure(self.state, {**self.development, "current_train": (self.x, self.y)})

    def test_all_candidates_actual_adam_zero_and_tampering_remain_explicit(self):
        state = self.state.clone()
        state.select_context("current_train")
        ref = build_reference(state, self.x, self.current_y,
                              ((self.x, self.current_y), (self.x, self.y)), horizon=8)
        models = {name: build_action_model(ref, observation=name) for name in ("full", "loss2")}
        anchor = self.state.head.loss_gradients(normalize_features(self.x), self.y, 0.0)[0]
        plans = plan_pressure(ref, models, anchor)
        self.assertEqual(len(plans), 13)
        results = execute_pressure(state, ref, plans, anchor)
        self.assertEqual(len(results), 13)
        manual = state.clone()
        for _ in range(8):
            manual.advance(self.x, self.current_y)
        self.assertEqual(results[0]["state"].digest(), manual.digest())
        self.assertNotEqual(results[0]["state"].digest(), state.digest())
        for row in results:
            if row["record"]["execution_status"] == "completed":
                self.assertEqual(row["state"].step_count, state.step_count + 8)
                self.assertGreaterEqual(row["record"]["execution_cpu_ns"], 0)
        modified = copy.deepcopy(plans)
        modified[0]["actions"][0, 0] = 1e-6
        failed = execute_pressure(state, ref, modified, anchor)
        self.assertEqual(failed[0]["record"]["execution_status"], "execution_failed")
        self.assertIsNone(failed[0]["state"])
        self.assertEqual(len(failed), 13)
        with self.assertRaises(ValueError):
            execute_pressure(state, ref, plans[:-1], anchor)

    def test_infeasible_small_box_is_not_converted_to_zero_execution(self):
        # Independent scalar constraint requires u>=0.5; the smallest box is .25.
        model = {"loss_maps": np.zeros((9, 2, 1)), "reference_observations": np.zeros((9, 2))}
        model["reference_observations"][1:, 1] = 0.5
        model["loss_maps"][1:, 1, 0] = -1.0
        ref = SimpleNamespace(horizon=8, state=SimpleNamespace(parameter_count=1, digest=lambda: "fixed"),
                              dt=0.02, observations=model["reference_observations"])
        plans = plan_pressure(ref, {"full": model}, 0.0)
        small = next(row for row in plans if row["record"]["budget_multiplier"] == 0.25
                     and row["record"]["objective"] == "direct_hard")
        self.assertEqual(small["record"]["status"], "tangent_infeasible")
        self.assertIsNone(small["actions"])
        self.assertGreater(small["record"]["solver_record"]["phase_one"]["witness_margin"], 0)
        wide = [row for row in plans if row["record"]["budget_multiplier"] in (1.0, 4.0)
                and row["record"]["objective"] == "direct_hard"]
        self.assertTrue(all(row["record"]["status"] == "planned" for row in wide))

    def test_five_predictors_integrate_with_common_baseline_and_complete_census(self):
        from cell_field_dynamics_v4 import build_prediction_models
        x = np.random.default_rng(901).normal(size=(12, 8))
        y = np.tile(np.arange(4), 3)
        state = CellTrainingState(NumpyCellHead(8, 4, "linear", seed=7),
                                 bindings={"fixture": "five-model-pressure-integration"})
        for _ in range(3):
            state.advance(x, y)
        reference = build_reference(state, x, y, ((x, y), (x, np.roll(y, 1))), horizon=8)
        models = build_prediction_models(reference)
        self.assertEqual(len(models), 5)
        anchor = float(reference.observations[0, 1])
        plans = plan_pressure(reference, models, anchor)
        self.assertEqual(len(plans), 31)
        self.assertFalse(any("reference_observations" in model for model in models.values()))
        results = execute_pressure(state, reference, plans, anchor)
        self.assertEqual(len(results), 31)
        for row in results:
            self.assertNotEqual(row["record"]["execution_status"], "execution_failed", row["record"])
            if row["record"]["execution_status"] == "completed":
                self.assertEqual(set(row["record"]["predicted_scores"]), set(models))


if __name__ == "__main__":
    unittest.main()
