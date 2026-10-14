"""Actual physical PyTorch Head calls behind nonauthorizing quarantine fence."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from amcn_core import Refused, digest
from amcn_guarded_shadow_worker import guarded_shadow_head_forward
from amcn_quarantine_ledger import ShadowQuarantineLedger, ZERO_SHA
from amcn_revocation import freeze_generation
from experiments.shared_stem_cell.execution import Head, parameters, tensor_digest
import test_amcn_revocation as fixture


class PreExecutionShadowHeadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = ShadowQuarantineLedger(Path(self.temp.name) / "owner")
        self.source = fixture.source("code_fault")
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            self.head = Head(4, 2, "linear", 2).eval().requires_grad_(False)
        trained_digest = parameters(self.head)["sha256"]
        self.artifact = freeze_generation(digest("physical-test-head"), "semantic_head",
                                          "tenant:lab", "g1", digest("stem"),
                                          trained_digest, (), (self.source,))
        self.args = dict(scope="tenant:lab", generation="g1")
        self.catalog = [self.artifact]
        self.physical_input = torch.tensor([[1., 0., 0., 0.]], dtype=torch.float32)
        self.first = self.ledger.apply(
            self.catalog, [self.source],
            externally_pinned_frontier_sha256=fixture.pinned([self.source]),
            expected_previous_sha256=ZERO_SHA, initialize=True, **self.args,
        )["metrics"]["journal_head_sha256"]

    def execute(self, *, sources=None, head=None, journal_head=None, artifact=None):
        current = [self.source] if sources is None else sources
        return guarded_shadow_head_forward(
            self.ledger, self.artifact if artifact is None else artifact,
            self.catalog, current,
            self.head if head is None else head, self.physical_input,
            externally_pinned_frontier_sha256=fixture.pinned(current),
            expected_journal_head_sha256=self.first if journal_head is None else journal_head,
            externally_pinned_feature_sha256=tensor_digest(self.physical_input),
            externally_pinned_encoder_sha256=digest("stem"),
            **self.args,
        )

    def test_actually_computes_small_head_without_product_authority(self):
        result = self.execute()
        self.assertEqual(len(result["probabilities"]), 1)
        self.assertTrue(0 <= result["probabilities"][0] <= 1)
        self.assertFalse(result["receipt"]["production_accepted"])
        self.assertTrue(result["receipt"]["metrics"]["local_quarantine_held_through_forward"])
        self.assertEqual(result["receipt"]["metrics"]["physical_head_calls"], 1)
        self.assertFalse(result["receipt"]["metrics"]["actual_source_owner_fenced"])

    def test_source_revocation_denies_without_head_forward(self):
        from unittest.mock import patch
        withdrawn = [replace(self.source, revoked=True)]
        second = self.ledger.apply(
            self.catalog, withdrawn,
            externally_pinned_frontier_sha256=fixture.pinned(withdrawn),
            expected_previous_sha256=self.first, **self.args,
        )["metrics"]["journal_head_sha256"]
        with patch.object(self.head, "forward", wraps=self.head.forward) as spy:
            with self.assertRaises(Refused):
                self.execute(sources=withdrawn, journal_head=second)
            spy.assert_not_called()

    def test_live_source_drift_requires_new_pinned_journal_before_model(self):
        changed = [replace(self.source, revision=2, content_sha256=digest("v2"))]
        with self.assertRaises(Refused):
            self.execute(sources=changed)

    def test_swapped_head_tensor_or_kind_cannot_reuse_artifact_id(self):
        with torch.no_grad():
            self.head.base.bias[0] += .1
        with self.assertRaises(Refused):
            self.execute()
        other = freeze_generation(self.artifact.artifact_id, "relation_router",
                                  "tenant:lab", "g1", digest("stem"),
                                  parameters(self.head)["sha256"], (), (self.source,))
        with self.assertRaises(Refused):
            self.execute(artifact=other)

    def test_mismatched_encoder_or_feature_pins_rejected_before_forward(self):
        from unittest.mock import patch
        args=dict(scope="tenant:lab", generation="g1")
        base = dict(
            ledger=self.ledger, artifact=self.artifact,
            all_artifacts=self.catalog, current_sources=[self.source],
            head=self.head, features=self.physical_input,
            externally_pinned_frontier_sha256=fixture.pinned([self.source]),
            expected_journal_head_sha256=self.first,
            externally_pinned_feature_sha256=tensor_digest(self.physical_input),
            externally_pinned_encoder_sha256=digest("stem"),
            **args,
        )
        for name, wrong in (("externally_pinned_feature_sha256", digest("wrong-input")),
                            ("externally_pinned_encoder_sha256", digest("wrong-stem"))):
            with self.subTest(pin=name), patch.object(self.head, "forward",
                                                      wraps=self.head.forward) as spy:
                bad = {**base, name: wrong}
                with self.assertRaises(Refused):
                    guarded_shadow_head_forward(**bad)
                spy.assert_not_called()

    def test_bad_batch_and_trainable_model_refuse_before_execution(self):
        self.head.train()
        with self.assertRaises(Refused):
            self.execute()
        self.head.eval().requires_grad_(True)
        with self.assertRaises(Refused):
            self.execute()
        self.head.requires_grad_(False)
        old = self.physical_input
        self.physical_input = torch.zeros((33, 4), dtype=torch.float32)
        try:
            with self.assertRaises(Refused):
                self.execute()
        finally:
            self.physical_input = old

    def test_crash_pending_fences_actual_head_execution(self):
        self.ledger.apply(
            self.catalog, [self.source],
            externally_pinned_frontier_sha256=fixture.pinned([self.source]),
            expected_previous_sha256=self.first, crash_at="prepared", **self.args,
        )
        with self.assertRaises(Refused):
            self.execute()


if __name__ == "__main__":
    unittest.main()
