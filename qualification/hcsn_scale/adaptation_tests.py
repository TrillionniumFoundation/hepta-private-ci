"""Tests of conditional optimality, envelope derivatives and rejection/KEEP."""

from copy import deepcopy
import json
import unittest

import torch

from qualification.hcsn_mechanism_v2.representation import ridge_fit
from .adaptation import (
    AdaptationConfig,
    adapt_model,
    collect_next_sensor,
    conditional_objective,
    fit_predictor,
)
from .model import ModelConfig, SequenceModel, tensor_map_digest


class AdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def problem(self):
        torch.manual_seed(17)
        model = SequenceModel(ModelConfig("gru", 2, 3, 1.0))
        windows = torch.randn(6, 4, 2, dtype=torch.float64) * 0.3
        intervals = torch.full(windows.shape[:2], 0.1, dtype=torch.float64)
        return model, windows, intervals

    def test_shared_conditional_solver_satisfies_normal_equations(self):
        model, windows, intervals = self.problem()
        with torch.no_grad():
            x, y = collect_next_sensor(model, windows, intervals)
        before = float(conditional_objective(model, x, y, 0.01).detach())
        diagnostics = fit_predictor(model, x, y, 0.01)
        for column in range(y.shape[1]):
            reference = ridge_fit(x, y[:, column], 0.01)
            torch.testing.assert_close(
                model.predictor.weight[column],
                reference["weight"],
                atol=2e-13,
                rtol=2e-13,
            )
            torch.testing.assert_close(
                model.predictor.bias[column], reference["bias"], atol=2e-13, rtol=2e-13
            )
        loss = conditional_objective(model, x, y, 0.01)
        loss.backward()
        self.assertLessEqual(float(loss.detach()), before + 1e-13)
        for parameter in model.predictor.parameters():
            self.assertLess(float(parameter.grad.abs().max()), 1e-11)
        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(x.shape, (18, 3))
        torch.testing.assert_close(y, windows[:, 1:].flatten(0, 1), atol=0, rtol=0)

    def test_profile_envelope_gradient_matches_resolved_finite_difference(self):
        model, windows, intervals = self.problem()
        x, y = collect_next_sensor(model, windows, intervals)
        fit_predictor(model, x, y, 0.03)
        parameter = model.encoder.weight_ih
        loss = conditional_objective(model, x, y, 0.03)
        gradient = torch.autograd.grad(loss, parameter)[0]
        index = int(gradient.abs().argmax())
        self.assertGreater(float(gradient.flatten()[index].abs()), 1e-8)
        objectives, epsilon = [], 1e-5
        for sign in (-1, 1):
            trial = deepcopy(model)
            with torch.no_grad():
                trial.encoder.weight_ih.flatten()[index] += sign * epsilon
                tx, ty = collect_next_sensor(trial, windows, intervals)
                fit_predictor(trial, tx, ty, 0.03)
                objectives.append(float(conditional_objective(trial, tx, ty, 0.03)))
        difference = (objectives[1] - objectives[0]) / (2 * epsilon)
        self.assertAlmostEqual(float(gradient.flatten()[index]), difference, delta=2e-8)

    def test_keep_and_dev_rejection_do_not_mutate_initial_weights(self):
        model, windows, intervals = self.problem()
        initial = tensor_map_digest(model.state_dict())
        for method in ("keep", "direct"):
            selected, report, states = adapt_model(
                model,
                windows,
                intervals,
                windows,
                intervals,
                method=method,
                config=AdaptationConfig(min_dev_improvement=100.0),
            )
            self.assertEqual(tensor_map_digest(model.state_dict()), initial)
            self.assertEqual(tensor_map_digest(selected.state_dict()), initial)
            self.assertEqual(report["selected_index"], 0)
            self.assertEqual(report["cost"]["backward_evaluations"], 0)
            self.assertIn(initial, states)
            json.dumps(report, allow_nan=False)

    def test_preservation_can_reject_a_dev_improvement(self):
        model, _, _ = self.problem()
        prefix = torch.tensor(
            [[0.2, 0.3], [0.5, -0.2], [-0.1, 0.4]], dtype=torch.float64
        )
        train = torch.stack((prefix, torch.ones_like(prefix)), 1)
        old = torch.stack((prefix, -torch.ones_like(prefix)), 1)
        dt = torch.full(train.shape[:2], 0.1, dtype=torch.float64)
        with torch.no_grad():
            model.predictor.weight.zero_()
            model.predictor.bias.zero_()
        selected, report, states = adapt_model(
            model,
            train,
            dt,
            train,
            dt,
            preservation=(old, dt),
            config=AdaptationConfig(preservation_tolerance=0.0),
        )
        candidate = report["candidates"][1]
        self.assertLess(candidate["dev_mse"], report["candidates"][0]["dev_mse"])
        self.assertEqual(candidate["reason"], "preservation tolerance exceeded")
        self.assertFalse(candidate["admissible"])
        self.assertEqual(report["selected_index"], 0)
        self.assertIn(candidate["state_digest"], states)
        self.assertEqual(
            tensor_map_digest(selected.state_dict()), report["initial_state_digest"]
        )

    def test_bounded_edit_records_rejection_without_solving_or_mutating(self):
        model, windows, intervals = self.problem()
        delta = torch.ones_like(model.encoder.weight_ih)
        _, report, _ = adapt_model(
            model,
            windows,
            intervals,
            windows,
            intervals,
            method="bounded_edit",
            edits=[{"encoder.weight_ih": delta}],
        )
        rejected = report["candidates"][1]
        self.assertEqual(rejected["reason"], "edit norm exceeds declared bound")
        self.assertEqual(report["cost"]["conditional_solves"], 0)
        self.assertEqual(report["selected_index"], 0)

    def test_valid_edit_is_installed_on_the_common_initial_encoder_and_charged(self):
        model, windows, intervals = self.problem()
        delta = torch.full_like(model.encoder.bias_hh, 0.005)
        original = model.encoder.bias_hh.detach().clone()
        _, report, states = adapt_model(
            model,
            windows,
            intervals,
            windows,
            intervals,
            method="bounded_edit",
            edits=[{"encoder.bias_hh": delta}, {"encoder.bias_hh": -delta}],
        )
        for candidate, sign in zip(report["candidates"][1:], (1, -1)):
            installed = states[candidate["state_digest"]]["encoder.bias_hh"]
            torch.testing.assert_close(
                installed, original + sign * delta, atol=0, rtol=0
            )
        torch.testing.assert_close(model.encoder.bias_hh, original, atol=0, rtol=0)
        self.assertEqual(report["cost"]["factorizations"], 2)
        self.assertEqual(report["cost"]["backward_evaluations"], 0)

    def test_profile_and_joint_charge_real_backward_and_keep_candidate_states(self):
        model, windows, intervals = self.problem()
        for method in ("profile_bp", "joint_bp"):
            selected, report, states = adapt_model(
                model,
                windows,
                intervals,
                windows,
                intervals,
                method=method,
                config=AdaptationConfig(steps=2),
            )
            self.assertEqual(report["cost"]["backward_evaluations"], 2)
            self.assertEqual(
                report["cost"]["factorizations"], report["cost"]["conditional_solves"]
            )
            self.assertEqual(
                report["cost"]["conditional_rhs"], 2 * report["cost"]["factorizations"]
            )
            self.assertEqual(len(report["candidates"]), 4)
            self.assertGreater(report["cost"]["total_seconds"], 0)
            self.assertEqual(
                tensor_map_digest(selected.state_dict()),
                report["selected_state_digest"],
            )
            self.assertEqual(report["test_queries"], 0)
            for candidate in report["candidates"]:
                self.assertEqual(
                    tensor_map_digest(states[candidate["state_digest"]]),
                    candidate["state_digest"],
                )
            json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
