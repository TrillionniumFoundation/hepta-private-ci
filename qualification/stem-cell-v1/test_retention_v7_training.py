"""Tiny CPU fixtures for V7 identities, matched streams, losses and failure costs."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from binding_continuation import continuation_plan
from binding_training import BindingTrainingFailure, _digest, balanced_group_batches, paired_margin_loss, world_pairs
from reader_features import tensor_digest
from retention_v7_training import ARMS, centered_logit_mse, continue_retention, make_retention_plan
from token_protocol import build_binding_cases
from token_reader import TokenReader
from token_reader_training import TokenBatch, parameter_digest


def data_for(cases, seed):
    generator = torch.Generator().manual_seed(seed)
    size = len(cases)
    return TokenBatch(facts=torch.randn(size, 4, 2, 8, generator=generator),
        question=torch.randn(size, 2, 8, generator=generator),
        candidate=torch.randn(size, 2, 8, generator=generator),
        fact_mask=torch.ones(size, 4, 2, dtype=torch.bool),
        question_mask=torch.ones(size, 2, dtype=torch.bool),
        candidate_mask=torch.ones(size, 2, dtype=torch.bool),
        targets=torch.tensor([case.label for case in cases]),
        source_groups=tuple(case.source_hash for case in cases))


class RetentionTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.old = build_binding_cases("train", groups=4, seed=3)
        self.aug = build_binding_cases("train", groups=4, seed=19)
        self.natural = tuple(replace(c, paragraph_id="natural-" + c.paragraph_id,
            source_hash=sha256(("natural-" + c.source_hash).encode()).hexdigest()) for c in self.old)
        self.binding, self.augmentation, self.natural_data = [
            data_for(cases, seed) for cases, seed in ((self.old, 5), (self.aug, 7), (self.natural, 11))]
        torch.manual_seed(23)
        self.model = TokenReader(8, 8, max_hops=3)
        self.model.training_source_groups = tuple(sorted(set(self.binding.source_groups)))
        with torch.no_grad():
            self.teacher = self.model(*self.binding.features(), steps=3).detach()
        self.plan = make_retention_plan(self.natural, self.old, self.aug, seed=41, updates=2)

    def fit(self, arm="anchored", **changes):
        arguments = dict(arm=arm, plan=self.plan, teacher_logits=self.teacher,
            teacher_logits_sha256=tensor_digest(self.teacher), natural_cases=self.natural,
            depth=3, diagnostic_interval=1, wall_time_ns=60_000_000_000)
        arguments.update(changes)
        return continue_retention(self.model, self.natural_data, self.binding, self.augmentation,
                                  self.old, self.aug, **arguments)

    def test_plan_preserves_v6_sequences_and_freezes_complete_augmentation_rows(self):
        original = continuation_plan(self.natural, self.old, seed=41, updates=2)
        self.assertEqual(self.plan["natural_batches"], original["natural_batches"])
        self.assertEqual(self.plan["binding_batches"], original["binding_batches"])
        self.assertEqual(self.plan["augmentation_batches"], balanced_group_batches(
            self.aug, updates=2, seed=41 ^ 0x713))
        self.assertEqual(self.plan["plan_sha256"], _digest(
            {k: v for k, v in self.plan.items() if k != "plan_sha256"}))
        self.assertEqual(self.plan["augmentation_case_ids"], [c.case_id for c in self.aug])
        with self.assertRaisesRegex(ValueError, "disjoint"):
            make_retention_plan(self.natural, self.old, self.old, seed=41, updates=2)

    def test_centered_loss_preserves_offsets_and_has_real_margin_gradient(self):
        student = torch.tensor([[1., 3.], [2., -1.]], requires_grad=True)
        teacher = student.detach().clone()
        self.assertEqual(centered_logit_mse(student + 17, teacher).item(), 0)
        changed = teacher.clone()
        changed[:, 1] += 2
        loss = centered_logit_mse(student, changed)
        self.assertGreater(loss.item(), 0)
        loss.backward()
        self.assertTrue(torch.isfinite(student.grad).all())
        self.assertGreater(student.grad.abs().sum().item(), 0)
        torch.testing.assert_close(student.grad.sum(-1), torch.zeros(2))

    def test_all_arms_execute_equal_natural_sequences_and_only_intended_loss_changes(self):
        original = parameter_digest(self.model)
        teacher_sha = tensor_digest(self.teacher)
        receipts = {}
        for arm in ARMS:
            trained, receipt = self.fit(arm)
            receipts[arm] = receipt
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["completed_steps"], 2)
            self.assertEqual(len(receipt["updates"]), 6)
            self.assertEqual([r["stream"] for r in receipt["updates"]],
                             ["natural", "transfer", "retention"] * 2)
            self.assertEqual(receipt["actual_total_exposures"], 96)
            self.assertFalse(trained.training)
            self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
            self.assertNotEqual(parameter_digest(trained), original)
            for row in receipt["updates"]:
                self.assertGreater(row["cpu_ns"], 0)
                self.assertTrue(row["finite_parameters_after_update"])
                self.assertEqual(row["inference_feature_arguments"], 6)
                self.assertEqual(row["anchor_weight"], float(arm == "anchored" and row["stream"] == "retention"))
                self.assertEqual(row["pair_weight"], 0 if row["stream"] == "natural" else .5)
            self.assertEqual(receipt["learning_rate"], .0001 if arm == "low_lr" else .001)
            self.assertEqual([r["case_ids"] for r in receipt["updates"] if r["stream"] == "transfer"],
                [[self.plan[("binding" if arm == "repeat" else "augmentation") + "_case_ids"][i]
                  for i in batch] for batch in self.plan[("binding" if arm == "repeat" else "augmentation") + "_batches"]])
        self.assertEqual(len({r["natural_sequence_sha256"] for r in receipts.values()}), 1)
        self.assertEqual(len({r["binding_sequence_sha256"] for r in receipts.values()}), 1)
        self.assertEqual(parameter_digest(self.model), original)
        self.assertEqual(tensor_digest(self.teacher), teacher_sha)

    def test_raw_step_logits_independently_reproduce_all_loss_components(self):
        _, receipt = self.fit()
        for row in receipt["updates"]:
            logits = torch.tensor(row["logits"])
            cases = self.natural if row["stream"] == "natural" else self.old if row["stream"] == "retention" else self.aug
            selected = [cases[i] for i in row["indices"]]
            ce = F.cross_entropy(logits, torch.tensor([c.label for c in selected]))
            pair = logits.new_zeros(()) if row["stream"] == "natural" else paired_margin_loss(
                logits, torch.tensor([c.label for c in selected]), world_pairs(selected))
            anchor = centered_logit_mse(logits, self.teacher[row["indices"]]) if row["stream"] == "retention" else logits.new_zeros(())
            self.assertAlmostEqual(row["binary_cross_entropy"], ce.item(), places=6)
            self.assertAlmostEqual(row["pair_loss"], pair.item(), places=6)
            self.assertAlmostEqual(row["anchor_mse"], anchor.item(), places=6)
            self.assertAlmostEqual(row["total_loss"], (ce + row["pair_weight"] * pair + anchor).item(), places=6)

    def test_invalid_teacher_and_changed_plan_are_rejected_before_copy(self):
        bad = {**self.plan, "augmentation_targets": [1-v for v in self.plan["augmentation_targets"]]}
        bad["plan_sha256"] = _digest({k: v for k, v in bad.items() if k != "plan_sha256"})
        attempts = [dict(teacher_logits=self.teacher.double()),
                    dict(teacher_logits=self.teacher.clone().requires_grad_()),
                    dict(teacher_logits_sha256="0" * 64), dict(plan=bad)]
        with patch("retention_v7_training._train_copy", side_effect=AssertionError("copy must not occur")) as copied:
            for changes in attempts:
                with self.assertRaises(BindingTrainingFailure) as caught:
                    self.fit(**changes)
                self.assertEqual(caught.exception.receipt["completed_steps"], 0)
                self.assertEqual(caught.exception.receipt["updates"], [])
            copied.assert_not_called()

    def test_failure_keeps_completed_stream_updates_and_immutable_original(self):
        data = self.natural_data
        class InterruptedNatural:
            targets, source_groups = data.targets, data.source_groups
            calls = 0
            def validate(self, input_dim):
                data.validate(input_dim)
            def take(self, indices):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("controlled natural batch failure")
                return data.take(indices)
        original, persisted = parameter_digest(self.model), []
        with self.assertRaises(BindingTrainingFailure) as caught:
            continue_retention(self.model, InterruptedNatural(), self.binding, self.augmentation,
                self.old, self.aug, arm="anchored", plan=self.plan, teacher_logits=self.teacher,
                teacher_logits_sha256=tensor_digest(self.teacher), natural_cases=self.natural,
                diagnostic_interval=1, failure_receipt_fn=persisted.append)
        self.assertEqual(persisted, [caught.exception.receipt])
        self.assertEqual(persisted[0]["completed_steps"], 1)
        self.assertEqual(len(persisted[0]["updates"]), 3)
        self.assertGreater(persisted[0]["cpu_ns"], 0)
        self.assertTrue(persisted[0]["failed_attempt_time_included"])
        self.assertEqual(parameter_digest(self.model), original)


if __name__ == "__main__":
    unittest.main()
