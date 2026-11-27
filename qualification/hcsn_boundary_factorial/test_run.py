"""Causal-intervention and actual-gradient checks for the finite pilot."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from .run import (ARMS, FactorialModel, batch, fit_one, make_optimizer,
                  paired_effects, prepare_data, tensor_digest)

SMALL_GRID = dict(active_cells=8, endpoint=2., phase_cells=4, refractory=.2,
                  tail_rate=1., quadrature_order=8, initial_log_std=.08)


class FactorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def inputs(self):
        with torch.random.fork_rng():
            torch.manual_seed(29)
            x = torch.randn(1, 3, 21, dtype=torch.float64)
        return (x, torch.tensor([[.02, .04, .06]], dtype=torch.float64),
                torch.ones(1, 3, dtype=torch.bool),
                torch.tensor([[1, 4, 2]], dtype=torch.long))

    def model(self, arm):
        return FactorialModel(11, arm, width=2, grid=SMALL_GRID)

    def test_four_arms_share_all_initial_tensor_bytes_and_predictions(self):
        models = [self.model(arm) for arm in ARMS]
        self.assertEqual(len({tensor_digest(model.state_dict()) for model in models}), 1)
        x, dt, valid, _ = self.inputs()
        with torch.no_grad():
            outputs = [model(x, dt, valid).predictions for model in models]
        self.assertTrue(all(torch.equal(outputs[0], value) for value in outputs[1:]))
        for arm, model in zip(ARMS, models):
            actual = set(model.trainable_names)
            boundary = {name for name in model.state_dict() if name.endswith("physics.raw_log_boundary")}
            content = {name for name, _ in model.named_parameters()
                       if any(part in name for part in ("write_gate.", "content_proposal.", "state_embedding"))}
            expected = (content if arm.startswith("c1") else set()) | (boundary if arm.endswith("b1") else set())
            self.assertEqual(actual, expected)
            self.assertEqual(len(model.network.layers), 1)
        self.assertIsNone(make_optimizer(models[0], .003))

    def test_pure_content_intervention_preserves_every_posterior(self):
        model = self.model("c1_b0")
        x, dt, valid, _ = self.inputs()
        with torch.no_grad():
            original = model(x, dt, valid, trace=True)
            for name, parameter in model.named_parameters():
                if name in model.trainable_names:
                    parameter.add_(.2)
            intervened = model(x, dt, valid, trace=True)
        self.assertTrue(all(torch.equal(left[0]["probability"], right[0]["probability"])
                            for left, right in zip(original.trace, intervened.trace)))
        self.assertFalse(torch.equal(original.state.layers[0].content_mass,
                                     intervened.state.layers[0].content_mass))

    def test_raw_boundary_loss_gradient_three_independent_fd_steps(self):
        model = self.model("c0_b1")
        x, dt, valid, y = self.inputs()
        parameter = model.network.layers[0].physics.raw_log_boundary
        initial = float(parameter.detach())
        loss = nn.functional.cross_entropy(model(x, dt, valid).predictions.flatten(0, 1),
                                           y.flatten())
        derivative, = torch.autograd.grad(loss, parameter)
        analytic = float(derivative)
        finite = []
        for h in (.001, .0003, .0001):
            values = []
            for sign in (-1., 1.):
                with torch.no_grad():
                    parameter.fill_(initial + sign * h)
                    logits = model(x, dt, valid).predictions
                    values.append(float(nn.functional.cross_entropy(logits.flatten(0, 1), y.flatten())))
            finite.append((values[1] - values[0]) / (2 * h))
        with torch.no_grad():
            parameter.fill_(initial)
        for value in finite:
            self.assertAlmostEqual(value, analytic, delta=2e-6 + 2e-3 * abs(analytic))
        self.assertLess(max(finite) - min(finite), 4e-6 + 4e-3 * abs(analytic))

    def test_optimizer_changes_only_declared_groups_and_restarts_episode(self):
        model = self.model("c1_b1")
        frozen = model.frozen_digest()
        before = {name: value.clone() for name, value in model.state_dict().items()}
        optimizer = make_optimizer(model, .003)
        x, dt, valid, y = self.inputs()
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            result = model(x, dt, valid)
            nn.functional.cross_entropy(result.predictions.flatten(0, 1), y.flatten()).backward()
            optimizer.step()
            self.assertEqual(model.frozen_digest(), frozen)
        changed = {name for name, value in model.state_dict().items()
                   if not torch.equal(value, before[name])}
        self.assertTrue(changed)
        self.assertTrue(changed.issubset(set(model.trainable_names)))
        self.assertIn("network.layers.0.physics.raw_log_boundary", changed)

    def test_frozen_physics_digest_detects_real_mutation(self):
        model = self.model("c1_b1")
        frozen = model.frozen_digest()
        with torch.no_grad():
            model.network.layers[0].physics.raw_mu.add_(.001)
        self.assertNotEqual(frozen, model.frozen_digest())

    def test_episode_padding_is_explicit_and_has_no_state_effect(self):
        x, dt, valid, y = self.inputs()
        row = dict(id="short", task="test", x=x[0].tolist(),
                   dt=dt[0].tolist(), y=y[0].tolist())
        longer = copy.deepcopy(row)
        longer["x"].append([0.] * 21)
        longer["dt"].append(.01)
        longer["y"].append(-1)
        combined = batch([row, longer])
        self.assertFalse(bool(combined[2][0, -1]))
        self.assertEqual(combined[1][0, -1].item(), 0.)
        self.assertEqual(combined[3][0, -1].item(), -1)
        model = self.model("c0_b0")
        with torch.no_grad():
            single = model(x, dt, valid)
            padded = model(*combined[:3])
        self.assertTrue(torch.allclose(single.predictions[0], padded.predictions[0, :3],
                                       atol=1e-14, rtol=1e-14))
        self.assertTrue(torch.allclose(single.state.layers[0].probability[0],
                                       padded.state.layers[0].probability[0],
                                       atol=1e-14, rtol=1e-14))

    def test_fixed_arm_real_forward_checkpoint_and_readback(self):
        x, dt, valid, y = self.inputs()
        row = dict(id="small", task="delayed_copy", x=x[0].tolist(),
                   dt=dt[0].tolist(), y=y[0].tolist())
        data = dict(train=[row], development=[row])
        config = dict(width=2, grid=SMALL_GRID, updates=2, learning_rate=.003)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixed"
            report = fit_one(config, 11, "c0_b0", data, "0" * 64, output, lambda: None)
            self.assertEqual(report["status"], "completed", report.get("error"))
            self.assertEqual(report["actual_optimizer_updates"], 0)
            self.assertEqual(report["training_forward_calls"], 2)
            self.assertTrue(report["checkpoint_replay_equal"])
            self.assertEqual(report["initialization_sha256"], report["final_model_sha256"])
            retained = torch.load(output / "checkpoint.pt", weights_only=True)
            self.assertIsNone(retained["optimizer"])
            records = (output / "training.jsonl").read_text().splitlines()
            self.assertEqual(len(records), 2)
            self.assertEqual(len(json.loads(records[0])["states"]), 3)

    def test_budget_failure_keeps_checkpoint_and_zero_completion_credit(self):
        data = prepare_data(1, 1)
        config = dict(width=2, grid=SMALL_GRID, updates=1, learning_rate=.003)
        def exhausted():
            raise TimeoutError("test budget")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed"
            report = fit_one(config, 11, "c0_b1", data, "0" * 64, output, exhausted)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["actual_optimizer_updates"], 0)
            self.assertEqual(report["training_forward_calls"], 0)
            self.assertFalse(report["complete_training_trace"])
            self.assertTrue((output / "checkpoint.pt").is_file())

    def test_symbolic_seeds_do_not_reuse_old_suite_ranges(self):
        data = prepare_data(2, 2)
        seeds = [row["seed"] for rows in data.values() for row in rows]
        self.assertEqual(len(seeds), len(set(seeds)))
        self.assertTrue(all(seed > 22561109 for seed in seeds))

    def test_paired_interaction_sign_and_missing_denominator(self):
        rows = [dict(seed=11, arm=arm, status="completed",
                     development=dict(cross_entropy=value))
                for arm, value in zip(ARMS, (5., 4., 3., 1.))]
        effect = paired_effects(rows, [11, 23])
        self.assertEqual(effect["expected_pairs"], 2)
        self.assertEqual(effect["complete_pairs"], 1)
        self.assertEqual(effect["per_seed"][0]["boundary_content_fixed"], 1.)
        self.assertEqual(effect["per_seed"][0]["boundary_content_learned"], 2.)
        self.assertEqual(effect["per_seed"][0]["interaction"], 1.)
        self.assertFalse(effect["inferential_claim"])


if __name__ == "__main__":
    unittest.main()
