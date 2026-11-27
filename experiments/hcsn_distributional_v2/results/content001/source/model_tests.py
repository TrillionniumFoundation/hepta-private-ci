"""Integration tests for distributional content, gradients and fair controls."""

import copy
import unittest

import torch
from torch.nn import functional as F

from .model import (DISTRIBUTION_ARMS, MODEL_NAMES, DistributionalClassifier,
                    _collapse_active, build_model)
from .distribution_kernel import Grid


class ContentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_task_loss_updates_all_five_groups(self):
        for arm in DISTRIBUTION_ARMS:
            with self.subTest(arm=arm), torch.random.fork_rng():
                torch.manual_seed(72)
                model = build_model(arm, 6, 3, width=12, seed=32)
                initial = {name: p.detach().clone() for name, p in model.named_parameters()}
                optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
                x, dt = torch.randn(3, 5, 6), torch.rand(3, 5) + 0.5
                y, aux = model(x, dt)
                loss = F.cross_entropy(y, torch.tensor([0, 1, 2]))
                loss.backward()
                seen = set()
                for group, entries in model.parameter_groups().items():
                    self.assertGreater(len(entries), 0, group)
                    self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                        for _, p in entries), group)
                    self.assertGreater(sum(float(p.grad.detach().square().sum())
                                           for _, p in entries), 0, group)
                    for name, _ in entries:
                        self.assertNotIn(name, seen)
                        seen.add(name)
                self.assertEqual(seen, set(initial))
                optimizer.step()
                for group, entries in model.parameter_groups().items():
                    self.assertGreater(sum(float((p.detach() - initial[name]).square().sum())
                                           for name, p in entries), 0, group)
                self.assertTrue(bool((aux["probability"] >= 0).all()))
                self.assertLess(float((aux["flow_mass"].detach() - 1).abs().max()), 2e-5)

    def test_precomputed_operator_matches_sequential_values_and_gradients(self):
        with torch.random.fork_rng():
            torch.manual_seed(41)
            first = DistributionalClassifier(5, 3, width=10, seed=53).double()
            second = copy.deepcopy(first)
            second.layers[0].precompute = False
            x, dt = torch.randn(2, 6, 5, dtype=torch.float64), torch.rand(2, 6, dtype=torch.float64)
            a, aa = first(x, dt, return_sequence=True)
            b, ba = second(x, dt, return_sequence=True)
            torch.testing.assert_close(a, b, atol=2e-10, rtol=2e-9)
            torch.testing.assert_close(aa["probability"], ba["probability"], atol=2e-10, rtol=2e-9)
            torch.testing.assert_close(aa["activity"], ba["activity"], atol=2e-10, rtol=2e-9)
            a.square().sum().backward()
            b.square().sum().backward()
            for (name, p), (_, q) in zip(first.named_parameters(), second.named_parameters(), strict=True):
                torch.testing.assert_close(p.grad, q.grad, atol=2e-8, rtol=2e-6, msg=name)

    def test_task_gradient_reaches_propagator_when_direct_parameter_features_detach(self):
        with torch.random.fork_rng():
            torch.manual_seed(328)
            model = DistributionalClassifier(6, 3, width=12, seed=35).double()
            layer = model.layers[0]
            def retain_probability_only(_, args):
                full = args[0].reshape(args[0].shape[0], layer.physical_channels, -1)
                retained = torch.cat((full[..., :10], full[..., 10:].detach()), -1)
                return (retained.flatten(1),)
            hooks = [layer.physical_gate.register_forward_pre_hook(retain_probability_only),
                     layer.feature_gate.register_forward_pre_hook(lambda _, args: (args[0].detach(),))]
            x, dt = torch.randn(3, 6, 6, dtype=torch.float64), torch.ones(3, 6, dtype=torch.float64)
            logits, _ = model(x, dt)
            F.cross_entropy(logits, torch.tensor([0, 1, 2])).backward()
            for group, entries in model.parameter_groups().items():
                if group != "content":
                    norm = sum(float(p.grad.detach().square().sum()) for _, p in entries if p.grad is not None)
                    self.assertGreater(norm, 0, group)
                    self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                        for _, p in entries), group)
            for hook in hooks:
                hook.remove()

    def test_streaming_recreates_batched_state(self):
        with torch.random.fork_rng():
            torch.manual_seed(8)
            model = DistributionalClassifier(5, 3, width=10, seed=83).double()
            x, dt = torch.randn(2, 7, 5, dtype=torch.float64), torch.rand(2, 7, dtype=torch.float64)
            batch, batch_aux = model(x, dt, return_sequence=True)
            state, outputs = None, []
            for index in range(x.shape[1]):
                logits, state, _ = model.step(x[:, index], dt[:, index], state)
                outputs.append(logits)
            torch.testing.assert_close(batch, torch.stack(outputs, 1), atol=2e-10, rtol=2e-9)
            for key in ("content", "probability", "boundary"):
                torch.testing.assert_close(batch_aux["state"]["layers"][0][key],
                                           state["layers"][0][key], atol=2e-10, rtol=2e-9)

    def test_unseen_suffix_and_batch_neighbor_do_not_change_prefix(self):
        with torch.random.fork_rng():
            torch.manual_seed(330)
            model = DistributionalClassifier(5, 3, width=10, seed=83).double()
            x, dt = torch.randn(2, 7, 5, dtype=torch.float64), torch.rand(2, 7, dtype=torch.float64)
            altered_x, altered_dt = x.clone(), dt.clone()
            altered_x[0, 4:] = 9*torch.randn_like(altered_x[0, 4:])
            altered_dt[0, 4:] = 3.5
            altered_x[1] = -15*torch.randn_like(altered_x[1])
            altered_dt[1] = 3.2
            a, aa = model(x, dt, return_sequence=True)
            b, ba = model(altered_x, altered_dt, return_sequence=True)
            torch.testing.assert_close(a[0, :4], b[0, :4], rtol=0, atol=0)
            torch.testing.assert_close(aa["probability"][0, :4], ba["probability"][0, :4], rtol=0, atol=0)

    def test_ordinary_arm_receives_identical_physical_information(self):
        dual = DistributionalClassifier(5, 3, width=10, seed=17)
        ordinary = DistributionalClassifier(5, 3, width=10, seed=17,
                                            arm="distribution_free_ordinary")
        self.assertEqual(set(dual.state_dict()), set(ordinary.state_dict()))
        for key, value in dual.state_dict().items():
            torch.testing.assert_close(value, ordinary.state_dict()[key], rtol=0, atol=0)
        captured = [[], []]
        hooks = [model.layers[0].physical_gate.register_forward_pre_hook(
            lambda _, args, slot=slot: captured[slot].append(args[0].detach().clone()))
            for slot, model in enumerate((dual, ordinary))]
        with torch.random.fork_rng():
            torch.manual_seed(31)
            x, dt = torch.randn(2, 5, 5), torch.rand(2, 5)
            dual(x, dt)
            ordinary(x, dt)
        for hook in hooks:
            hook.remove()
        self.assertEqual(len(captured[0]), 5)
        for a, b in zip(*captured, strict=True):
            torch.testing.assert_close(a, b, rtol=0, atol=0)

    def test_collapse_preserves_mass_mean_and_each_phase(self):
        grid = Grid(cells=8, lower=-2, refractory_stages=2)
        torch.manual_seed(911)
        p = torch.rand(3, 4, 10, dtype=torch.float64)
        p = p / p.sum(-1, keepdim=True)
        boundary = torch.rand(3, 4, dtype=torch.float64) + 1
        q = _collapse_active(p, boundary, grid)
        centers = grid.lower + (boundary-grid.lower)[..., None] / grid.cells * (
            torch.arange(grid.cells, dtype=torch.float64)+0.5)
        torch.testing.assert_close(p.sum(-1), q.sum(-1), atol=1e-15, rtol=1e-14)
        torch.testing.assert_close(p[..., 8:], q[..., 8:], rtol=0, atol=0)
        torch.testing.assert_close((p[..., :8]*centers).sum(-1),
                                   (q[..., :8]*centers).sum(-1), atol=1e-15, rtol=1e-14)

    def test_frontends_readouts_and_parameter_tolerance(self):
        reference = build_model(MODEL_NAMES[0], 64, 8, seed=9201)
        target = reference.counts()["backbone"]
        for name in MODEL_NAMES:
            model = build_model(name, 64, 8, seed=9201)
            self.assertLess(abs(model.counts()["backbone"]-target)/target, 0.03, name)
            for module in ("frontend", "readout"):
                for key, value in getattr(reference, module).state_dict().items():
                    torch.testing.assert_close(value, getattr(model, module).state_dict()[key],
                                               rtol=0, atol=0, msg=name)


if __name__ == "__main__":
    unittest.main()
