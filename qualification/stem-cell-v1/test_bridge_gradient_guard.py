"""Actual small-Torch numerical tests; not pretrained learning efficacy."""
import copy
import hashlib
import math
import sys
import types
import unittest

import torch
from torch import nn

from bridge_gradient_guard import combine_gradients, gradient_step, continue_candidate, ARMS


class DummyBatch:
    def __init__(self, features, labels):
        self.x = torch.tensor(features, dtype=torch.float32)
        self.targets = torch.tensor(labels, dtype=torch.long)

    def features(self):
        return (self.x,)


class DummyReader(nn.Module):
    max_hops = 3
    def __init__(self):
        super().__init__()
        self.proj = nn.Linear(2, 2, bias=False)
        self.calls = 0

    def forward(self, x, *, steps):
        self.calls += 1
        return self.proj(x)


class GradientTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_negative_conflict_removed_first_order(self):
        old = (torch.tensor([1., 0.]),)
        new = (torch.tensor([-1., 1.]),)
        g, d = combine_gradients(old, new, arm="protect_old")
        self.assertEqual(g[0].tolist(), [1., 1.])
        self.assertTrue(d["projected"])
        self.assertAlmostEqual(d["residual_new_dot_old"], 0.)

    def test_control_preserves_conflict(self):
        g, d = combine_gradients((torch.tensor([1., 0.]),),
                                 (torch.tensor([-2., 1.]),), arm="joint")
        self.assertEqual(g[0].tolist(), [-1., 1.])
        self.assertFalse(d["projected"])
        self.assertLess(d["residual_new_dot_old"], 0)

    def test_aligned_or_orthogonal_gradient_is_not_changed(self):
        for new in ([1., 3.], [0., 2.]):
            g, d = combine_gradients((torch.tensor([1., 0.]),),
                                     (torch.tensor(new),), arm="protect_old")
            self.assertEqual(g[0].tolist(), [1+new[0], new[1]])
            self.assertFalse(d["projected"])

    def test_zero_old_gradient_finite(self):
        g, d = combine_gradients((torch.zeros(2),),
                                 (torch.tensor([-2., 1.]),), arm="protect_old")
        self.assertEqual(g[0].tolist(), [-2., 1.])
        self.assertFalse(d["projected"])

    def test_tensor_mismatch_and_invalid_arm_fail(self):
        with self.assertRaises(ValueError):
            combine_gradients((torch.zeros(2),), (torch.zeros(3),), arm="protect_old")
        with self.assertRaises(ValueError):
            combine_gradients((torch.zeros(2),), (torch.zeros(2),), arm="unsafe")
        with self.assertRaises(ValueError):
            combine_gradients((torch.zeros(2),), (), arm="joint")

    def test_nonfinite_rejected_without_reinterpretation(self):
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                combine_gradients((torch.tensor([value]),), (torch.ones(1),), arm="joint")

    def test_real_torch_two_loss_two_backward_equal_budget(self):
        # Minimal module stub for the imported *existing* V6 paired margin owner.
        # The real campaign uses binding_training.paired_margin_loss unchanged.
        fake = types.ModuleType("binding_training")
        fake.paired_margin_loss = lambda z, y, pairs: ((z[:, 1] - z[:, 0]) ** 2).mean()
        former = sys.modules.get("binding_training")
        sys.modules["binding_training"] = fake
        try:
            start = DummyReader().train()
            parent = copy.deepcopy(start.state_dict())
            natural = DummyBatch([[1., 0.], [0., 1.]], [0, 1])
            new = DummyBatch([[1., 1.], [-1., -1.]], [1, 0])
            results = []
            for arm in ARMS:
                model = copy.deepcopy(start).train()
                optimizer = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
                record = gradient_step(model, optimizer, natural, new, ((0, 1),), arm=arm,
                                       depth=3, max_gradient_norm=1.)
                self.assertEqual(model.calls, 2)
                self.assertEqual(record["actual_reader_forwards"], 2)
                self.assertEqual(record["actual_backward_calls"], 2)
                self.assertEqual(record["old_train_rows"], 2)
                self.assertEqual(record["new_train_rows"], 2)
                self.assertTrue(math.isfinite(record["preclip_combined_l2"]))
                self.assertNotEqual(model.state_dict()["proj.weight"].tolist(), parent["proj.weight"].tolist())
                results.append(record)
            self.assertEqual(results[0]["optimizer_steps"], results[1]["optimizer_steps"])
            self.assertEqual(start.calls, 0)
            self.assertTrue(torch.equal(start.state_dict()["proj.weight"], parent["proj.weight"]))
        finally:
            if former is None:
                del sys.modules["binding_training"]
            else:
                sys.modules["binding_training"] = former


    def test_two_step_candidate_keeps_parent_frozen_with_full_accounting(self):
        fake_bind = types.ModuleType("binding_training")
        fake_bind.paired_margin_loss = lambda z, y, pairs: ((z[:, 1] - z[:, 0]) ** 2).mean()
        fake_bind.world_pairs = lambda cases: ((0, 1),)
        fake_cont = types.ModuleType("binding_continuation")
        fake_cont.validate_continuation_plan = lambda *args, **kwargs: None
        fake_digest = types.ModuleType("token_reader_training")
        fake_digest.parameter_digest = lambda m: hashlib.sha256(b"".join(
            t.detach().contiguous().numpy().tobytes() for t in m.state_dict().values())).hexdigest()
        names = ("binding_training", "binding_continuation", "token_reader_training")
        originals = {name: sys.modules.get(name) for name in names}
        sys.modules.update(zip(names, (fake_bind, fake_cont, fake_digest)))
        try:
            class Dataset:
                source_groups = ("original-train-only",)
                targets = torch.tensor([0, 1])
                def take(self, indices):
                    return DummyBatch([[1., 0.], [0., 1.]], [0, 1])
            parent = DummyReader().eval().requires_grad_(False)
            parent.input_dim = 2
            parent.training_source_groups = ("frozen-original",)
            model_hash = fake_digest.parameter_digest(parent)
            plan = dict(updates=2, plan_sha256="a" * 64,
                natural_case_ids=["old-a", "old-b"],
                binding_case_ids=["new-a", "new-b"],
                natural_batches=[[0, 1], [0, 1]],
                binding_batches=[[0, 1], [0, 1]])
            for arm in ARMS:
                candidate, r = continue_candidate(parent, Dataset(), Dataset(),
                    [object(), object()], plan=plan, arm=arm,
                    original_natural_cases=None)
                self.assertEqual(r["actual_reader_forwards"], 4)
                self.assertEqual(r["actual_backward_calls"], 4)
                self.assertEqual(r["optimizer_steps"], 2)
                self.assertEqual(r["old_train_rows"], 4)
                self.assertEqual(r["new_train_rows"], 4)
                self.assertEqual(r["trainable_parameter_count"], 4)
                self.assertTrue(r["status"] == "completed" and not r["production_authorized"])
                self.assertFalse(candidate.training)
                self.assertTrue(all(not p.requires_grad for p in candidate.parameters()))
                self.assertNotEqual(fake_digest.parameter_digest(candidate), model_hash)
                self.assertEqual(fake_digest.parameter_digest(parent), model_hash)
        finally:
            for name, original in originals.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

    def test_training_boundary_rejects_frozen_model(self):
        model = DummyReader().eval().requires_grad_(False)
        batch = DummyBatch([[0., 1.]], [1])
        with self.assertRaisesRegex(ValueError, "trainable"):
            gradient_step(model, torch.optim.Adam(model.parameters()), batch, batch,
                          ((0, 0),), arm="joint")

    def test_hyperparameter_boundary(self):
        model = DummyReader().train()
        batch = DummyBatch([[0., 1.]], [1])
        for kwargs in ({"depth":0}, {"max_gradient_norm":0},
                       {"pair_weight":0.0}, {"arm":"invalid"}):
            with self.assertRaises(ValueError):
                gradient_step(model, torch.optim.Adam(model.parameters()),
                              batch, batch, ((0, 0),), **({"arm":"joint"} | kwargs))


if __name__ == '__main__':
    unittest.main()
