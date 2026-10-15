"""Actual Torch numerical + stdlib independent-review tests (no pretrained claims)."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch
from torch import nn
from torch.nn import functional as F

from bridge_gradient_guard import (
    ARMS, OLD_TASK, NEW_TASK, combine_gradients, gradient_step,
    continue_candidate,
)
from bridge_gradient_review import check_gradient_rows, _digest, _retention, read


class Batch:
    def __init__(self, features, targets):
        self.x = torch.tensor(features, dtype=torch.float32)
        self.targets = torch.tensor(targets, dtype=torch.long)

    def features(self):
        return (self.x,)


class Reader(nn.Module):
    max_hops = 3
    input_dim = 2

    def __init__(self):
        super().__init__()
        self.linear = nn.Linear(2, 2, bias=False)
        self.calls = 0

    def forward(self, x, *, steps):
        self.calls += 1
        return self.linear(x)


class Dataset:
    source_groups = ("approved-train-source",)
    targets = torch.tensor([0, 1, 1, 0])

    def take(self, indices):
        items = [[1., 0.], [0., 1.], [-1., 0.], [0., -1.]]
        return Batch([items[i] for i in indices], [self.targets[i] for i in indices])


class RealPairedLossStub:
    """Test-scoped reproduction of original binding_training.paired_loss math."""
    def __enter__(self):
        module = types.ModuleType("binding_training")
        def real_formula(logits, targets, pairs):
            left, right = [torch.tensor(side, dtype=torch.long) for side in zip(*pairs)]
            scores = logits[:, 1] - logits[:, 0]
            signed = (2*targets[left]-1) * (scores[left]-scores[right])
            return F.softplus(1. - signed).mean()
        module.paired_margin_loss = real_formula
        module.world_pairs = lambda cases: ((0,2), (1,3))
        self.original = sys.modules.get("binding_training")
        sys.modules["binding_training"] = module
        return module

    def __exit__(self, *_):
        if self.original is None:
            sys.modules.pop("binding_training", None)
        else:
            sys.modules["binding_training"] = self.original


def batches():
    old = Batch([[1., 0.], [0., 1.], [-1., 0.], [0., -1.]], [0, 1, 1, 0])
    new = Batch([[1., 1.], [-1., -1.], [1., -1.], [-1., 1.]], [1, 0, 1, 0])
    return old, new


class GradientTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_old_binding_role_is_explicit_and_not_natural(self):
        self.assertIn("binding", OLD_TASK)
        self.assertIn("natural", NEW_TASK)
        self.assertEqual(len(ARMS), 3)

    def test_negative_conflict_removed_first_order(self):
        old = (torch.tensor([1., 0.]),)
        new = (torch.tensor([-1., 1.]),)
        for arm in ("protect_old", "protect_old_guarded"):
            g, info = combine_gradients(old, new, arm=arm)
            self.assertEqual(g[0].tolist(), [1., 1.])
            self.assertTrue(info["projected"])
            self.assertAlmostEqual(info["residual_new_dot_old"], 0.)

    def test_joint_preserves_negative_conflict(self):
        g, info = combine_gradients((torch.tensor([1., 0.]),),
                                    (torch.tensor([-2., 1.]),), arm="joint")
        self.assertEqual(g[0].tolist(), [-1., 1.])
        self.assertFalse(info["projected"])
        self.assertLess(info["residual_new_dot_old"], 0)

    def test_nonconflict_and_zero_old_gradient(self):
        for new in ([1., 3.], [0., 2.]):
            g, info = combine_gradients((torch.tensor([1., 0.]),),
                                        (torch.tensor(new),), arm="protect_old")
            self.assertEqual(g[0].tolist(), [1.+new[0], new[1]])
            self.assertFalse(info["projected"])
        g, info = combine_gradients((torch.zeros(2),),
                                    (torch.tensor([-2., 1.]),), arm="protect_old")
        self.assertEqual(g[0].tolist(), [-2., 1.])
        self.assertFalse(info["projected"])

    def test_finite_shape_dtype_and_arm_mismatches(self):
        pairs = [((torch.ones(2),), (torch.ones(3),), "protect_old"),
                 ((torch.ones(2),), (torch.ones(2),), "wrong"),
                 ((torch.ones(2),), (), "joint"),
                 ((torch.ones(2,dtype=torch.float64),), (torch.ones(2),), "joint"),
                 ((torch.tensor([float("nan")]),), (torch.ones(1),), "joint"),
                 ((torch.tensor([float("inf")]),), (torch.ones(1),), "joint")]
        for old, new, arm in pairs:
            with self.subTest(arm=arm, value=old[0].tolist()):
                with self.assertRaises(ValueError):
                    combine_gradients(old, new, arm=arm)

    def test_three_physical_forwards_two_backward_and_right_task(self):
        with RealPairedLossStub():
            torch.manual_seed(8)
            frozen = Reader().eval().requires_grad_(False)
            start = copy.deepcopy(frozen.state_dict())
            old, new = batches()
            for arm in ARMS:
                model = copy.deepcopy(frozen).train().requires_grad_(True)
                optim = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
                row = gradient_step(model, optim, old, new, ((0,2),(1,3)), arm=arm)
                self.assertEqual(model.calls, 3)
                self.assertEqual(row["actual_reader_forwards"], 3)
                self.assertEqual(row["actual_backward_calls"], 2)
                self.assertEqual(row["old_task"], OLD_TASK)
                self.assertEqual(row["new_task"], NEW_TASK)
                self.assertEqual(row["old_train_rows"], 4)
                self.assertEqual(row["new_train_rows"], 4)
                self.assertAlmostEqual(row["old_loss_before"],
                    row["old_ce"]+.5*row["old_pair_loss"],places=6)
                self.assertTrue(math.isfinite(row["old_loss_after_proposal"]))
                self.assertEqual(row["accepted_optimizer_steps"]+row["rejected_optimizer_steps"], 1)
            self.assertTrue(torch.equal(frozen.linear.weight, start["linear.weight"]))
            self.assertEqual(frozen.calls, 0)

    def test_guard_reverts_actual_adam_overshoot_and_optimizer_moments(self):
        with RealPairedLossStub():
            old, new = batches()
            torch.manual_seed(42)
            for learning_rate in (2., 5., 10., 20.):
                model = Reader().train()
                before = model.linear.weight.detach().clone()
                optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, foreach=False)
                row = gradient_step(model, optimizer, old, new, ((0,2),(1,3)),
                                    arm="protect_old_guarded")
                if row["old_loss_guard_reverted"]:
                    self.assertGreater(row["old_loss_proposal_delta"], 1e-6)
                    self.assertTrue(torch.equal(model.linear.weight, before))
                    self.assertEqual(len(optimizer.state), 0)
                    return
            self.fail("test requires a real rejected high-lr Adam update")

    def test_guard_restores_nonempty_adam_moments_and_step_number(self):
        with RealPairedLossStub():
            old, new = batches()
            torch.manual_seed(42)
            model = Reader().train()
            optimizer = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
            first = gradient_step(model, optimizer, old, new, ((0,2),(1,3)),
                                  arm="protect_old_guarded")
            self.assertEqual(first["accepted_optimizer_steps"], 1)
            original_params = [p.detach().clone() for p in model.parameters()]
            original_state = copy.deepcopy(optimizer.state_dict())
            optimizer.param_groups[0]["lr"] = 2.
            second = gradient_step(model, optimizer, old, new, ((0,2),(1,3)),
                                   arm="protect_old_guarded")
            self.assertEqual(second["rejected_optimizer_steps"], 1)
            self.assertTrue(all(torch.equal(p, before) for p, before in
                                zip(model.parameters(), original_params)))
            actual_state = optimizer.state_dict()
            for key, before in original_state["state"].items():
                for name, value in before.items():
                    observed = actual_state["state"][key][name]
                    if isinstance(value, torch.Tensor):
                        self.assertTrue(torch.equal(value, observed))
                    else:
                        self.assertEqual(value, observed)

    def test_old_paired_loss_cannot_silently_attach_to_new_natural_batch(self):
        old, new = batches()
        with RealPairedLossStub() as binding:
            original = binding.paired_margin_loss
            calls = []
            def checked(logits, targets, pairs):
                self.assertTrue(torch.equal(targets, old.targets))
                calls.append(1)
                return original(logits, targets, pairs)
            binding.paired_margin_loss = checked
            model = Reader().train()
            optimizer = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
            gradient_step(model, optimizer, old, new, ((0,2),(1,3)), arm="joint")
            # once pre-Adam and once post-Adam; no pair loss on natural/new.
            self.assertEqual(len(calls), 2)

    def test_unprotected_arm_records_actual_adam_old_loss(self):
        with RealPairedLossStub():
            old, new = batches()
            model = Reader().train()
            optimizer = torch.optim.Adam(model.parameters(), lr=10., foreach=False)
            row = gradient_step(model, optimizer, old, new, ((0,2),(1,3)), arm="joint")
            self.assertEqual(row["rejected_optimizer_steps"], 0)
            self.assertFalse(row["old_loss_guard_reverted"])
            self.assertGreater(row["old_loss_after_proposal"], 0)

    def test_boundary_rejects_inactive_and_bad_hyperparameters(self):
        model = Reader().eval().requires_grad_(False)
        old, new = batches()
        with self.assertRaisesRegex(ValueError, "trainable"):
            gradient_step(model, torch.optim.Adam(model.parameters()), old, new,
                          ((0,2),(1,3)), arm="joint")
        model.train().requires_grad_(True)
        for change in ({"depth":0}, {"pair_weight":0.0}, {"arm":"invalid"},
                       {"max_gradient_norm":0}, {"post_step_tolerance":float("nan")},
                       {"post_step_tolerance":.5}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    gradient_step(model, torch.optim.Adam(model.parameters()), old, new,
                                  ((0,2),(1,3)), **({"arm":"joint"} | change))

    def test_candidate_copy_and_binding_old_schedule(self):
        fake_cont = types.ModuleType("binding_continuation")
        fake_cont.validate_continuation_plan = lambda *args, **kwargs: None
        fake_digest = types.ModuleType("token_reader_training")
        fake_digest.parameter_digest = lambda m: hashlib.sha256(b"".join(
            t.detach().contiguous().numpy().tobytes() for t in m.state_dict().values())).hexdigest()
        originals = {name:sys.modules.get(name) for name in ("binding_continuation", "token_reader_training")}
        sys.modules["binding_continuation"] = fake_cont
        sys.modules["token_reader_training"] = fake_digest
        try:
            with RealPairedLossStub():
                parent = Reader().eval().requires_grad_(False)
                start_sha = fake_digest.parameter_digest(parent)
                parent.training_source_groups = ("old-binding",)
                plan = dict(updates=2, plan_sha256="a"*64,
                    natural_case_ids=[f"natural-{i}" for i in range(4)],
                    binding_case_ids=[f"binding-{i}" for i in range(4)],
                    natural_batches=[[0,1,2,3]]*2,
                    binding_batches=[[0,1,2,3]]*2)
                for arm in ARMS:
                    model, receipt = continue_candidate(parent, Dataset(), Dataset(),
                        [object() for _ in range(4)], plan=plan, arm=arm)
                    self.assertEqual(receipt["actual_reader_forwards"], 6)
                    self.assertEqual(receipt["actual_backward_calls"], 4)
                    self.assertEqual(receipt["attempted_optimizer_steps"], 2)
                    self.assertEqual(receipt["old_train_rows"], receipt["new_train_rows"])
                    self.assertEqual(receipt["updates"][0]["old_case_ids"], plan["binding_case_ids"])
                    self.assertEqual(receipt["updates"][0]["new_case_ids"], plan["natural_case_ids"])
                    self.assertEqual(receipt["accepted_optimizer_steps"]+receipt["rejected_optimizer_steps"],2)
                    self.assertTrue(receipt["status"] == "completed" and not receipt["production_authorized"])
                    self.assertFalse(model.training)
                    self.assertTrue(all(not p.requires_grad for p in model.parameters()))
                    self.assertEqual(fake_digest.parameter_digest(parent), start_sha)
        finally:
            for name, old in originals.items():
                if old is None:sys.modules.pop(name,None)
                else:sys.modules[name]=old

    def test_independent_complete_record_replay_and_inversion_tamper(self):
        with RealPairedLossStub():
            old, new = batches()
            model = Reader().train()
            optimizer = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
            one = gradient_step(model, optimizer, old, new, ((0,2),(1,3)), arm="protect_old")
        plan = {"plan_sha256":"a"*64, "updates":2,
                "binding_case_ids":[f"binding-{i}" for i in range(4)],
                "natural_case_ids":[f"natural-{i}" for i in range(4)],
                "binding_batches":[[0,1,2,3]]*2,
                "natural_batches":[[0,1,2,3]]*2}
        steps = []
        for i in range(2):
            steps.append(dict(one, logical_step=i+1,
                old_case_ids=plan["binding_case_ids"], new_case_ids=plan["natural_case_ids"]))
        receipt = dict(schema="hepta.bridge.gradient-continuation.v7.1", status="completed",
            arm="protect_old", old_task=OLD_TASK, new_task=NEW_TASK,
            plan_sha256=plan["plan_sha256"], source_scope="original_train_only",
            production_authorized=False, updates=steps, old_train_batches=2, new_train_batches=2,
            attempted_optimizer_steps=2, accepted_optimizer_steps=2, rejected_optimizer_steps=0,
            actual_reader_forwards=6, actual_backward_calls=4, old_train_rows=8,
            new_train_rows=8, cpu_ns=2*one["cpu_ns"]+100_000,
            wall_ns=2*one["wall_ns"]+100_000, equal_backward_calls=True,
            actual_compute_equal=False, old_task_retention_verified=False,
            natural_task_generalization_verified=False)
        work = check_gradient_rows(receipt, plan, "protect_old", steps=2)
        self.assertEqual(work["forwards"],6)
        mutated = copy.deepcopy(receipt)
        mutated["updates"][0]["old_case_ids"] = plan["natural_case_ids"]
        with self.assertRaisesRegex(ValueError, "sources"):
            check_gradient_rows(mutated,plan,"protect_old",steps=2)
        mutated = copy.deepcopy(receipt)
        mutated["updates"][0]["old_gradient_squared_l2"] += 20.
        with self.assertRaisesRegex(ValueError, "scalar replay mismatch"):
            check_gradient_rows(mutated,plan,"protect_old",steps=2)
        mutated = copy.deepcopy(receipt)
        mutated["updates"][0]["accepted_optimizer_steps"] = 0
        with self.assertRaisesRegex(ValueError, "guard/rollback"):
            check_gradient_rows(mutated,plan,"protect_old",steps=2)

    def test_source_only_retention_gate_and_unsafe_report_denial(self):
        self.assertTrue(_retention({"accuracy":.96,"both_worlds_correct":.97},
                                   {"accuracy":1.,"both_worlds_correct":1.}))
        self.assertFalse(_retention({"accuracy":.96,"both_worlds_correct":.93},
                                    {"accuracy":1.,"both_worlds_correct":1.}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"bad.json"
            path.write_text('{"x":1,"x":2}')
            with self.assertRaisesRegex(ValueError,"duplicate"):
                read(path)
            path.write_text('{"x":NaN}')
            with self.assertRaisesRegex(ValueError,"nonfinite"):
                read(path)


if __name__ == '__main__':
    unittest.main()
