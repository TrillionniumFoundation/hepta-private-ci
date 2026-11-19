"""Small deterministic checks of paired fitting and continuation accounting."""
from dataclasses import replace
import unittest

import torch
from torch import nn

from binding_training import (BindingTrainingFailure, balanced_group_batches, binding_groups,
    fit_binding_reader, paired_margin_loss, world_pairs)
from token_protocol import build_binding_cases
from token_reader_training import TokenBatch, parameter_digest


class PublicReader(nn.Module):
    """A tiny fixture exposing exactly the six public inference arguments."""
    input_dim, max_hops = 8, 3

    def __init__(self):
        super().__init__()
        self.project = nn.Linear(8, 8)
        self.head = nn.Linear(8, 2)

    def forward(self, facts, question, candidate, fact_mask, question_mask, candidate_mask,
                *, steps=1, return_attention=False):
        state = torch.tanh(self.project(facts.mean((1, 2))))
        states = []
        for _ in range(steps):
            state = torch.tanh(state + .1)
            states.append(state)
        logits = self.head(state)
        return dict(logits=logits, states=states) if return_attention else logits


def fixture():
    cases = build_binding_cases("train", groups=4, seed=3)
    torch.manual_seed(5)
    data = TokenBatch(facts=torch.randn(16, 4, 2, 8), question=torch.randn(16, 2, 8),
        candidate=torch.randn(16, 2, 8), fact_mask=torch.ones(16, 4, 2, dtype=torch.bool),
        question_mask=torch.ones(16, 2, dtype=torch.bool), candidate_mask=torch.ones(16, 2, dtype=torch.bool),
        targets=torch.tensor([case.label for case in cases]), source_groups=tuple(case.source_hash for case in cases))
    return cases, data


class BindingTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.cases, self.data = fixture()

    def test_pair_loss_is_invariant_to_world_and_row_order(self):
        logits = torch.randn(16, 2, requires_grad=True)
        first = paired_margin_loss(logits, self.data.targets, world_pairs(self.cases))
        permutation = torch.tensor([7, 1, 11, 4, 14, 3, 13, 6, 5, 10, 0, 12, 15, 8, 2, 9])
        cases = tuple(self.cases[index] for index in permutation.tolist())
        second = paired_margin_loss(logits[permutation], self.data.targets[permutation], world_pairs(cases))
        torch.testing.assert_close(first, second)
        first.backward()
        self.assertTrue(torch.isfinite(logits.grad).all())
        aligned = torch.tensor([[0., 3.] if target else [3., 0.] for target in self.data.targets])
        self.assertLess(paired_margin_loss(aligned, self.data.targets, world_pairs(self.cases)).item(), first.item())

    def test_bad_worlds_and_label_bindings_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete worlds"):
            binding_groups(self.cases[:-1])
        changed = list(self.cases)
        changed[2] = replace(changed[2], label=changed[0].label)
        with self.assertRaisesRegex(ValueError, "opposite labels"):
            binding_groups(changed)
        changed = list(self.cases)
        changed[2] = replace(changed[2], candidate="The changed box.")
        with self.assertRaisesRegex(ValueError, "opposite labels"):
            binding_groups(changed)
        data = replace(self.data, targets=1 - self.data.targets)
        with self.assertRaisesRegex(BindingTrainingFailure, "labels and source order"):
            fit_binding_reader(PublicReader(), data, self.cases, steps=1)

    def test_sampling_covers_whole_groups_uniformly_each_epoch(self):
        batches = balanced_group_batches(self.cases, updates=8, batch_size=4, seed=7)
        self.assertEqual(batches, balanced_group_batches(self.cases, updates=8, batch_size=4, seed=7))
        for start in (0, 4):
            self.assertEqual(sorted(index for batch in batches[start:start + 4] for index in batch), list(range(16)))
        for batch in batches:
            self.assertEqual(len(binding_groups([self.cases[index] for index in batch])), 1)

    def test_fit_keeps_input_frozen_and_counts_actual_public_feature_updates(self):
        model = PublicReader().eval().requires_grad_(False)
        original = parameter_digest(model)
        trained, receipt = fit_binding_reader(model, self.data, self.cases, steps=2,
            batch_size=8, diagnostic_interval=1, wall_time_ns=30_000_000_000)
        self.assertEqual(parameter_digest(model), original)
        self.assertEqual(receipt["initial_model_sha256"], original)
        self.assertEqual(receipt["completed_steps"], 2)
        self.assertEqual(receipt["actual_training_exposures"], 16)
        self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        self.assertGreater(receipt["cpu_ns"], 0)
        self.assertEqual(len(receipt["diagnostics"]), 3)
        self.assertTrue(all(row["inference_feature_arguments"] == 6 for row in receipt["updates"]))
        self.assertTrue(all(row["finite_gradients"] for row in receipt["updates"]))
        self.assertFalse(receipt["official_validation_evaluated"])
        self.assertIsNone(receipt["formula_flops"])

    def test_failed_materialization_retains_partial_update_costs(self):
        data = self.data

        class Interrupted:
            targets, source_groups = data.targets, data.source_groups
            calls = 0

            def validate(self, input_dim):
                return data.validate(input_dim)

            def take(self, indices):
                self.calls += 1
                if self.calls == 3:
                    raise RuntimeError("intentional materialization interruption")
                return data.take(indices)

        persisted = []
        with self.assertRaises(BindingTrainingFailure) as captured:
            fit_binding_reader(PublicReader(), Interrupted(), self.cases, steps=3,
                batch_size=16, diagnostic_interval=3, failure_receipt_fn=persisted.append)
        receipt = captured.exception.receipt
        self.assertEqual(receipt, persisted[0])
        self.assertEqual(receipt["completed_steps"], 1)
        self.assertEqual(receipt["actual_training_exposures"], 16)
        self.assertGreater(receipt["cpu_ns"], 0)
        self.assertTrue(receipt["failed_attempt_time_included"])
        self.assertFalse(receipt["final_evaluation_authorized"])


    def test_continuation_arms_share_initial_checkpoint_and_minibatch_streams(self):
        from binding_continuation import continuation_plan, continue_binding_reader
        natural_cases = build_binding_cases("train", groups=4, seed=7)
        natural = replace(self.data, targets=torch.tensor([case.label for case in natural_cases]),
                          source_groups=tuple(case.source_hash for case in natural_cases))
        plan = continuation_plan(natural_cases, self.cases, seed=41, updates=2, batch_size=8)
        model = PublicReader().eval().requires_grad_(False)
        digest = parameter_digest(model)
        receipts = {}
        for arm in ("natural_only", "replay", "contrastive"):
            trained, receipt = continue_binding_reader(model, natural, self.data, self.cases,
                arm=arm, plan=plan, natural_diagnostic=natural.take([0, 1, 2, 3]), diagnostic_interval=1)
            receipts[arm] = receipt
            self.assertEqual(receipt["initial_model_sha256"], digest)
            self.assertEqual(receipt["completed_natural_updates"], 2)
            self.assertEqual(receipt["actual_natural_exposures"], 16)
            self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        self.assertEqual(parameter_digest(model), digest)
        natural_streams = [[row["case_ids"] for row in r["updates"] if row["stream"] == "natural"]
                           for r in receipts.values()]
        self.assertEqual(natural_streams[0], natural_streams[1])
        self.assertEqual(natural_streams[1], natural_streams[2])
        binding_streams = [[row["case_ids"] for row in receipts[arm]["updates"] if row["stream"] == "binding"]
                           for arm in ("replay", "contrastive")]
        self.assertEqual(binding_streams[0], binding_streams[1])
        self.assertEqual(receipts["natural_only"]["completed_binding_updates"], 0)
        self.assertEqual(receipts["replay"]["completed_binding_updates"], 2)
        self.assertEqual(receipts["contrastive"]["actual_total_exposures"], 32)
        self.assertEqual(receipts["contrastive"]["pair_weight"], .5)

    def test_changed_plan_and_nontraining_diagnostics_are_rejected(self):
        from binding_continuation import continuation_plan, continue_binding_reader
        natural_cases = build_binding_cases("train", groups=4, seed=7)
        natural = replace(self.data, targets=torch.tensor([case.label for case in natural_cases]),
                          source_groups=tuple(case.source_hash for case in natural_cases))
        plan = continuation_plan(natural_cases, self.cases, seed=41, updates=1, batch_size=8)
        with self.assertRaisesRegex(BindingTrainingFailure, "subset of training"):
            continue_binding_reader(PublicReader(), natural, self.data, self.cases,
                                    arm="replay", plan=plan, natural_diagnostic=self.data)
        with self.assertRaisesRegex(BindingTrainingFailure, "natural case identity"):
            continue_binding_reader(PublicReader(), natural, self.data, self.cases, arm="replay", plan=plan,
                                    natural_cases=tuple(reversed(natural_cases)))
        plan["natural_batches"][0].reverse()
        with self.assertRaisesRegex(BindingTrainingFailure, "digest changed"):
            continue_binding_reader(PublicReader(), natural, self.data, self.cases, arm="replay", plan=plan)


if __name__ == "__main__":
    unittest.main()
