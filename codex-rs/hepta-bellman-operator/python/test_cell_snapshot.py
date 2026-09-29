"""Snapshot ABA regressions using real tiny Torch heads, not Laya efficacy.

The clock callback models another owner mutating borrowed tensors exactly at an
allocation boundary. Restoring borrowed bytes later must not certify different
bytes in the private copy as the original dataset or base model.
"""
from dataclasses import replace
import hashlib
import unittest
from unittest.mock import patch

import torch
from torch import nn

from cell_head import (HeadBudget, HeadRejected, HeadRow, fit_head,
                       state_digest, validate_rows)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(91)
        self.head = nn.Sequential(nn.LayerNorm(4), nn.Linear(4, 4),
                                  nn.GELU(), nn.Linear(4, 1)).eval().requires_grad_(False)
        self.objective, self.bundle = sha("objective"), sha("bundle")
        self.rows = tuple(HeadRow(
            f"row.{i}", f"group.{i}", 1000 + i, "workspace.1",
            self.objective, self.bundle, sha(f"source.{i}"), sha(f"outcome.{i}"),
            ("abstain", "a", "b"),
            torch.tensor([[1., 0., 2., -1.], [0., 2., -1., 1.], [-1., 1., 0., 2.]]),
            torch.tensor([0., float(i == 0), float(i == 1)])) for i in range(2))

    def fit(self, clock=lambda: 100., rows=None, budget=None):
        return fit_head(self.head, self.rows if rows is None else rows,
                        scope="workspace.1", objective=self.objective,
                        bundle=self.bundle, temperature=1., budget=budget or HeadBudget(),
                        deadline=200., clock=clock)

    def aba_clock(self, change, restore, change_call=3, restore_call=4):
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            if calls == change_call:
                change()
            if calls == restore_call:
                restore()
            return 100.
        return clock

    def reject_borrowed_aba(self, tensor, changed):
        original = tensor.clone()
        before = state_digest(self.head)
        dataset = validate_rows(self.rows, 4, "workspace.1", self.objective, self.bundle)
        clock = self.aba_clock(lambda: tensor.copy_(changed), lambda: tensor.copy_(original))
        try:
            with self.assertRaisesRegex(HeadRejected, "snapshot|copied"):
                self.fit(clock)
        finally:
            tensor.copy_(original)
        self.assertEqual(before, state_digest(self.head))
        self.assertEqual(dataset, validate_rows(self.rows, 4, "workspace.1", self.objective, self.bundle))

    def test_target_aba_cannot_certify_the_original_dataset(self):
        self.reject_borrowed_aba(self.rows[0].target, torch.tensor([0., 0., 1.]))

    def test_feature_aba_cannot_certify_the_original_dataset(self):
        self.reject_borrowed_aba(self.rows[0].features, self.rows[0].features.flip(0).contiguous())

    def test_base_parameter_aba_cannot_certify_the_original_model(self):
        self.reject_borrowed_aba(self.head[1].weight, self.head[1].weight.detach().clone() + .125)

    def test_base_schema_aba_cannot_certify_the_original_model(self):
        original = self.head[0].eps
        clock = self.aba_clock(lambda: setattr(self.head[0], "eps", .2),
                               lambda: setattr(self.head[0], "eps", original))
        try:
            with self.assertRaisesRegex(HeadRejected, "snapshot|copied"):
                self.fit(clock)
        finally:
            self.head[0].eps = original

    def test_after_snapshot_transient_target_mutation_does_not_change_training(self):
        clean = self.fit()
        tensor, original = self.rows[0].target, self.rows[0].target.clone()
        clock = self.aba_clock(lambda: tensor.copy_(torch.tensor([0., 0., 1.])),
                               lambda: tensor.copy_(original), 5, 6)
        try:
            candidate = self.fit(clock)
        finally:
            tensor.copy_(original)
        self.assertEqual(clean.dataset_digest, candidate.dataset_digest)
        self.assertEqual(clean.candidate_head_digest, candidate.candidate_head_digest)
        self.assertEqual(clean.payload, candidate.payload)
        self.assertEqual(clean.steps, candidate.steps)

    def test_no_data_and_insufficient_groups_allocate_no_candidate(self):
        with patch("cell_head.copy.deepcopy", side_effect=AssertionError("candidate allocated")):
            for rows in ((), (self.rows[0],)):
                fit = self.fit(rows=rows)
                self.assertEqual(fit.disposition, "no_change")
                self.assertEqual(fit.steps, 0)
                self.assertIsNone(fit.payload)

    def test_budget_rejects_before_any_tensor_copy(self):
        with patch.object(torch.Tensor, "clone", side_effect=AssertionError("tensor copied")):
            with self.assertRaisesRegex(HeadRejected, "budget"):
                self.fit(budget=replace(HeadBudget(), owned_tensor_bytes=1))

    def test_unrestored_source_drift_remains_rejected(self):
        tensor, original = self.rows[0].target, self.rows[0].target.clone()
        clock = self.aba_clock(lambda: tensor.copy_(torch.tensor([0., 0., 1.])),
                               lambda: None, 5, 1000)
        try:
            with self.assertRaisesRegex(HeadRejected, "dataset changed"):
                self.fit(clock)
        finally:
            tensor.copy_(original)


if __name__ == "__main__":
    unittest.main()
