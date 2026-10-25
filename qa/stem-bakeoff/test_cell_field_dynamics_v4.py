"""Real Head/Adam integration on bounded test data; no efficacy claim."""

import copy
import json
import unittest

import numpy as np

from cell_field_control import build_reference
from cell_field_dynamics_v4 import (
    MODEL_NAMES, adam_direction_jacobians, adam_direction_observation,
    build_prediction_models,
)
from cell_field_fixed_actions import fixed_library
from cell_field_fixed_adapter import fixed_impulse_predictions
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class FivePredictorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7463)
        old, current = rng.normal(size=(32, 8)), rng.normal(size=(32, 8))
        old_y, current_y = np.tile(np.arange(4), 8), np.roll(np.tile(np.arange(4), 8), 1)
        cls.refs, cls.models = {}, {}
        for mode in ("linear", "gated"):
            state = CellTrainingState(
                NumpyCellHead(8, 4, mode, seed=127), bindings={"test": "v4-real-class"},
                contexts={"old": dataset_digest(old, old_y),
                          "current": dataset_digest(current, current_y)}, active_context="old")
            for _ in range(11):
                state.advance(old, old_y)
            state.select_context("current")
            ref = build_reference(state, current, current_y,
                                  ((current, current_y), (old, old_y)), horizon=8)
            cls.refs[mode] = ref
            cls.models[mode] = build_prediction_models(ref)

    def test_inherited_predictions_match_for_all_49_impulses(self):
        for mode, ref in self.refs.items():
            models = self.models[mode]
            self.assertEqual(tuple(models), MODEL_NAMES)
            for action_id, action in fixed_library(ref.state.parameter_count):
                for name in ("loss2", "q4", "full"):
                    predicted = np.einsum("kij,j->ki", models[name]["loss_maps"], action)
                    inherited = fixed_impulse_predictions(ref, action_id, mode=name)["fields"]
                    np.testing.assert_allclose(predicted, inherited, rtol=2e-10, atol=2e-12)
            for model in models.values():
                json.dumps(model["metadata"], allow_nan=False)
                np.testing.assert_array_equal(model["loss_maps"][0], 0)
                np.testing.assert_allclose(model["loss_maps"][1], models["full"]["loss_maps"][1], atol=2e-12)

    def test_full_forecast_matches_nonlinear_impulse_derivative(self):
        for mode, ref in self.refs.items():
            p = ref.state.parameter_count
            action = np.asarray(dict(fixed_library(p))["d2:a1/2:s1"])
            epsilon = 1e-4
            paths = []
            for sign in (-1, 1):
                x = ref.states[0].copy()
                losses = [ref.observe(x)[0][:2]]
                for k in range(ref.horizon):
                    x = ref.state.transition_vector(x, ref.state.step_count+k,
                                                    ref.train_features, ref.train_labels)
                    if k == 0:
                        x[:p] += sign*epsilon*ref.dt*action
                    losses.append(ref.observe(x)[0][:2])
                paths.append(np.asarray(losses))
            derivative = (paths[1]-paths[0])/(2*epsilon)
            predicted = np.einsum("kij,j->ki", self.models[mode]["full"]["loss_maps"], action)
            np.testing.assert_allclose(predicted, derivative, rtol=3e-3, atol=2e-7)

    def test_structured_jacobian_matches_independent_all_column_difference(self):
        for ref in self.refs.values():
            jacobians, audit = adam_direction_jacobians(ref)
            p = ref.state.parameter_count
            self.assertLess(max(row["theta_half_step_relative_difference"] for row in audit), 1e-6)
            for k in (0, 4, 8):
                x = ref.states[k]
                fd = np.zeros_like(jacobians[k])
                for j in range(len(x)):
                    delta = 1e-5*ref.scales[j]
                    if j >= 2*p:
                        delta = min(delta, 0.01*x[j])
                    self.assertGreater(delta, 0)
                    plus, minus = x.copy(), x.copy()
                    plus[j] += delta
                    minus[j] -= delta
                    fd[:, j] = ((adam_direction_observation(ref, plus, k)
                                 - adam_direction_observation(ref, minus, k))
                                * ref.scales[j]/(2*delta))
                np.testing.assert_allclose(jacobians[k], fd, rtol=2e-3, atol=2e-8)
            self.assertGreater(np.linalg.norm(jacobians[:, 2:, 2*p:]), 0)

    def test_history_uses_known_action_and_transition_relationship(self):
        for mode, ref in self.refs.items():
            models = self.models[mode]
            # With zero anchor displacement and the known first impulse, the
            # reconstructed state at step one is exactly E0*u, irrespective of
            # observation rank. A naive independent delay lift lacks this fact.
            np.testing.assert_allclose(models["history4"]["loss_maps"][:3],
                                       models["full"]["loss_maps"][:3], atol=2e-12)
            self.assertGreater(np.linalg.norm(models["history4"]["loss_maps"]
                                              - models["loss2"]["loss_maps"]), 1e-8)
            self.assertEqual(models["history4"]["metadata"]["previous_action_memory_bytes"],
                             8*ref.state.parameter_count)

    def test_build_is_pure_and_rejects_coordinate_drift(self):
        ref = self.refs["linear"]
        before = ref.state.digest()
        arrays = [v.copy() for v in (ref.A, ref.C, ref.states, ref.scales)]
        build_prediction_models(ref)
        self.assertEqual(before, ref.state.digest())
        for old, current in zip(arrays, (ref.A, ref.C, ref.states, ref.scales)):
            np.testing.assert_array_equal(old, current)
        changed = copy.deepcopy(ref)
        changed.scales *= 2
        with self.assertRaises(ValueError):
            build_prediction_models(changed)
        with self.assertRaises(ValueError):
            build_prediction_models(object())

    def test_h1_subset_does_not_build_unrequested_models(self):
        from unittest.mock import patch
        original = self.refs["linear"]
        ref = build_reference(original.state, original.train_features, original.train_labels,
                              original.probes, horizon=1, dt=original.dt)
        with patch("cell_field_dynamics_v4.adam_direction_jacobians", side_effect=AssertionError):
            model = build_prediction_models(ref, names=("full",))
        self.assertEqual(tuple(model), ("full",))
        for action_id, action in fixed_library(ref.state.parameter_count):
            np.testing.assert_allclose(
                np.einsum("kij,j->ki", model["full"]["loss_maps"], action),
                fixed_impulse_predictions(ref, action_id, mode="full")["fields"], atol=2e-12)
        for invalid in ((), ("full", "full"), ("full", "loss2"), ("unknown",)):
            with self.assertRaises(ValueError):
                build_prediction_models(ref, names=invalid)


if __name__ == "__main__":
    unittest.main()
