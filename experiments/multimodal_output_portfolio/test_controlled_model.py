"""Behavioral checks for controlled generation and its exact loss gradients."""

from dataclasses import FrozenInstanceError
import unittest

import numpy as np
import torch

from controlled_model import (ControlledOutputModel, evaluation_loss_table,
                              external_loss_tensor, loss_table, train_controlled)
from model import MODALITIES, OutputModel, _weight_hashes


class ControlledModelTests(unittest.TestCase):
    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(731)
            self.base = OutputModel(dict(zip(MODALITIES, (16, 20, 24, 28)))).eval()
        rng = np.random.default_rng(1981)
        self.canonical = {name: rng.normal(size=(8, width)).astype(np.float32)
                          for name, width in self.base.dimensions.items()}
        self.q = torch.eye(8)

    def test_original_depth_three_and_actual_intermediate_outputs(self):
        controlled = ControlledOutputModel(self.base)
        outputs = controlled.outputs_by_depth(self.q)
        expected = self.base(self.q)
        self.assertEqual(len(outputs), 4)
        for name in MODALITIES:
            self.assertTrue(torch.equal(outputs[3][name], expected[name]))
            self.assertFalse(torch.equal(outputs[0][name], outputs[1][name]))
            self.assertFalse(torch.equal(outputs[1][name], outputs[2][name]))
            self.assertFalse(torch.equal(outputs[2][name], outputs[3][name]))
            self.assertEqual(outputs[0][name].shape, (8, self.base.dimensions[name]))

    def test_stream_is_immutable_and_emission_cannot_be_rewound(self):
        controlled = ControlledOutputModel(self.base)
        q = self.q.clone()
        initial = controlled.initialize(q)
        snapshot = initial.latent.detach().clone()
        q.zero_()
        initial.latent.add_(20)
        self.assertTrue(torch.equal(initial.latent, snapshot))
        with self.assertRaises(FrozenInstanceError):
            initial.depth = 1
        current = controlled.refine_step(initial)
        self.assertTrue(torch.equal(initial.latent, snapshot))
        with self.assertRaisesRegex(ValueError, "stale"):
            controlled.refine_step(initial)
        self.assertEqual(set(controlled.emit(current)), set(MODALITIES))
        self.assertTrue(initial.sealed and current.sealed)
        for state in (initial, current):
            with self.assertRaisesRegex(ValueError, "sealed"):
                controlled.refine_step(state)
            with self.assertRaisesRegex(ValueError, "sealed"):
                controlled.emit(state)
        fresh = controlled.initialize(self.q)
        self.assertFalse(fresh.sealed)

    def test_invalid_portfolios_depth_and_cross_generator_states(self):
        controlled = ControlledOutputModel(self.base)
        invalid = [np.empty((0, 8)), np.ones((1, 9)), np.zeros((2, 8)),
                   np.full((1, 8), np.nan), np.full((1, 8), np.inf),
                   np.array([[-1, 2, 0, 0, 0, 0, 0, 0]]),
                   np.ones((1, 8), dtype=complex), torch.ones((1, 8), dtype=torch.bool)]
        for value in invalid:
            with self.subTest(value=str(value)):
                with self.assertRaises(ValueError):
                    controlled.initialize(value)
        other = ControlledOutputModel(self.base)
        with self.assertRaisesRegex(ValueError, "another"):
            controlled.refine_step(other.initialize(self.q))
        for depth in (True, -1, 4, 1.5):
            with self.assertRaises(ValueError):
                controlled.outputs_by_depth(self.q, depth)
        state = controlled.initialize(self.q)
        for _ in range(3):
            state = controlled.refine_step(state)
        with self.assertRaisesRegex(ValueError, "maximum"):
            controlled.refine_step(state)
        with self.assertRaises(TypeError):
            controlled.refine_step(state, self.canonical)

    def test_smooth_loss_reaches_shared_field_and_all_decoders(self):
        q = self.q.clone().requires_grad_(True)
        table = loss_table(self.base, q, self.canonical)
        self.assertEqual(table.shape, (4, 8, 8))
        self.assertTrue(torch.isfinite(table).all())
        table.mean().backward()
        for module in (self.base.initial_latent, self.base.refinement,
                       *self.base.decoders.values()):
            gradients = [parameter.grad for parameter in module.parameters()]
            self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in gradients))
            self.assertGreater(sum(float(g.abs().sum()) for g in gradients), 0)
        self.assertTrue(all(p.grad is None for p in self.base.encoders.parameters()))
        self.assertTrue(torch.isfinite(q.grad).all())
        self.assertGreater(float(q.grad.abs().sum()), 0)

    def test_finite_difference_of_exact_external_loss_away_from_boundaries(self):
        self.base.double()
        q = self.q.double()
        table = external_loss_tensor(self.base, q, self.canonical)
        scalar = table[:, :, 0].mean()
        scalar.backward()
        parameter = self.base.initial_latent.weight
        analytic = float(parameter.grad[0, 0])
        original = float(parameter[0, 0])
        delta = 1e-5
        estimates = []
        with torch.no_grad():
            for perturbation in (delta, -delta):
                parameter[0, 0] = original + perturbation
                estimates.append(float(external_loss_tensor(
                    self.base, q, self.canonical)[:, :, 0].mean()))
            parameter[0, 0] = original
        finite_difference = (estimates[0] - estimates[1]) / (2 * delta)
        self.assertGreater(abs(analytic), 1e-9)
        self.assertAlmostEqual(analytic, finite_difference, delta=1e-7)

    def test_external_loss_parity_including_clips_and_contradictions(self):
        ordinary = external_loss_tensor(self.base, self.q, self.canonical)
        np.testing.assert_allclose(
            ordinary.detach().numpy(),
            evaluation_loss_table(self.base, self.q, self.canonical), rtol=0, atol=2e-6)
        with torch.no_grad():
            for index, name in enumerate(MODALITIES):
                final = self.base.decoders[name][-1]
                final.weight.zero_()
                final.bias.copy_(torch.as_tensor(self.canonical[name][index]))
            self.base.decoders["video"][-1].bias.fill_(50)
        tensor = external_loss_tensor(self.base, self.q, self.canonical)
        expected = evaluation_loss_table(self.base, self.q, self.canonical)
        np.testing.assert_allclose(tensor.detach().numpy(), expected, rtol=0, atol=2e-6)
        smooth = loss_table(self.base, self.q, self.canonical)
        self.assertGreater(float(smooth.max()), float(tensor.max()) + 1)
        missing = dict(self.canonical)
        missing.pop("text")
        with self.assertRaises(ValueError):
            loss_table(self.base, self.q, missing)
        no_variation = dict(self.canonical, text=np.zeros((8, 16)))
        with self.assertRaisesRegex(ValueError, "semantic variation"):
            loss_table(self.base, self.q, no_variation)

    def test_warmup_updates_copy_and_counts_executed_linear_work(self):
        self.base.requires_grad_(False)
        original_hashes = _weight_hashes(self.base)
        observed_macs = []

        def record(module, args, _output):
            rows = args[0].numel() // module.in_features
            observed_macs.append(rows * module.in_features * module.out_features)

        hooks = [module.register_forward_hook(record) for module in self.base.modules()
                 if isinstance(module, torch.nn.Linear)]
        trained, receipt = train_controlled(self.base, self.canonical, seed=19,
                                             steps=3, batch_size=16)
        for hook in hooks:
            hook.remove()
        self.assertEqual(original_hashes, _weight_hashes(self.base))
        self.assertEqual(receipt["parameter_groups_changed"],
                         {"all": True, "encoders": False,
                          "shared_refinement": True, "decoders": True})
        self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        self.assertTrue(np.isfinite(receipt["final_probe_depth_mse"]).all())
        self.assertEqual(sum(observed_macs), receipt["training_forward_linear_macs"]
                         + receipt["diagnostic_forward_linear_macs"])


if __name__ == "__main__":
    unittest.main()
