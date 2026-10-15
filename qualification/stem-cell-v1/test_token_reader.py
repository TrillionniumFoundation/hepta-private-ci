import itertools
import unittest

import torch
from torch.nn import functional as F

from token_reader import TokenReader, _sigmoid, _tanh
from token_reader_training import TokenBatch, TokenTrainingFailure, fit_token_reader, parameter_digest


def binding_batch():
    """Identical question/candidate pairs have opposing labels across evidence."""
    facts, questions, candidates, targets, groups, attention = [], [], [], [], [], []
    for index, assignment in enumerate(itertools.product((0, 1), repeat=3)):
        for asked in range(3):
            for candidate in range(2):
                row = torch.zeros(3, 2, 8)
                for key, value in enumerate(assignment):
                    row[key, 0, key], row[key, 1, 3 + value] = 1, 1
                facts.append(row)
                questions.append(F.one_hot(torch.tensor(asked), 8).float().unsqueeze(0))
                candidates.append(F.one_hot(torch.tensor(3 + candidate), 8).float().unsqueeze(0))
                targets.append(int(assignment[asked] == candidate))
                groups.append("training-assignment-" + str(index))
                attention.append(F.one_hot(torch.tensor(asked), 3).float())
    return TokenBatch(facts=torch.stack(facts), question=torch.stack(questions),
        candidate=torch.stack(candidates), fact_mask=torch.ones(48, 3, 2, dtype=torch.bool),
        question_mask=torch.ones(48, 1, dtype=torch.bool),
        candidate_mask=torch.ones(48, 1, dtype=torch.bool), targets=torch.tensor(targets),
        source_groups=tuple(groups), evidence_targets=torch.stack(attention),
        evidence_supervision=torch.ones(48, dtype=torch.bool))


class TokenReaderTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(7)
        self.batch = binding_batch()

    def test_padding_deleted_evidence_and_empty_candidate(self):
        model, batch = TokenReader(8, 16), self.batch.take([0, 1])
        result = model(*batch.features(), steps=3, return_attention=True)
        permutation = torch.tensor([2, 0, 1])
        permuted = model(batch.facts[:, permutation], batch.question, batch.candidate,
                         batch.fact_mask[:, permutation], batch.question_mask, batch.candidate_mask, steps=3)
        torch.testing.assert_close(result["logits"], permuted)
        padded_facts = torch.cat((batch.facts, torch.randn(2, 1, 2, 8) * 1000), 1)
        padded_mask = torch.cat((batch.fact_mask, torch.zeros(2, 1, 2, dtype=torch.bool)), 1)
        padded = model(padded_facts, batch.question, batch.candidate, padded_mask,
                       batch.question_mask, batch.candidate_mask, steps=3)
        torch.testing.assert_close(result["logits"], padded)
        empty = model(batch.facts, batch.question, batch.candidate, torch.zeros_like(batch.fact_mask),
            batch.question_mask, torch.zeros_like(batch.candidate_mask), steps=3, return_attention=True)
        self.assertTrue(torch.equal(empty["attentions"][0], torch.zeros(2, 3)))
        self.assertTrue(torch.isfinite(empty["logits"]).all())
        self.assertLessEqual(empty["state"].abs().max().item(), 1)
        with self.assertRaisesRegex(ValueError, "state"):
            model(*batch.features(), state=torch.full((2, 16), 2.))

    def test_pooled_ablation_keeps_parameters_and_prepare_matches_forward(self):
        token, pooled = TokenReader(8, 16), TokenReader(8, 16, interaction="pooled")
        pooled.load_state_dict(token.state_dict())
        self.assertEqual(parameter_digest(token), parameter_digest(pooled))
        batch = self.batch.take([0, 1, 2])
        prepared = token.prepare(*batch.features())
        state = None
        for _ in range(3):
            state, logits, _, _ = token.step_prepared(prepared, state)
        torch.testing.assert_close(logits, token(*batch.features(), steps=3))
        self.assertEqual(len(batch.model_args()), 6)
        self.assertFalse(torch.equal(token(*batch.features()), pooled(*batch.features())))

    def test_controlled_binding_learns_evidence_and_training_receipts(self):
        original = TokenReader(8, 16)
        initial_hash = parameter_digest(original)
        model, receipt = fit_token_reader(original, self.batch, steps=250, seed=11,
            batch_size=48, max_depth=2, learning_rate=.01, evidence_weight=.1,
            diagnostic_interval=250, wall_time_ns=60_000_000_000)
        prediction = model(*self.batch.features(), steps=2).argmax(-1)
        self.assertEqual(prediction.tolist(), self.batch.targets.tolist())
        deleted = model(self.batch.facts, self.batch.question, self.batch.candidate,
            torch.zeros_like(self.batch.fact_mask), self.batch.question_mask,
            self.batch.candidate_mask, steps=2).argmax(-1)
        self.assertEqual(deleted.eq(self.batch.targets).float().mean().item(), .5)
        self.assertEqual(parameter_digest(original), initial_hash)
        self.assertEqual(receipt["model_sha256"], parameter_digest(model))
        self.assertEqual(receipt["completed_steps"], 250)
        self.assertEqual(receipt["actual_training_exposures"], 250 * 48)
        self.assertEqual(receipt["intervention_update_probability"], 0)
        self.assertGreater(receipt["cpu_ns"], 0)
        self.assertGreater(receipt["optimizer_tensor_bytes"], 0)
        self.assertIsNone(receipt["formula_flops"])
        self.assertTrue(all(not parameter.requires_grad for parameter in model.parameters()))
        self.assertTrue(all(row["parameter_gradient_l2"] > 0 for row in receipt["updates"]))
        self.assertTrue(any(len(row["hop_state_gradient_l2"]) == 2 for row in receipt["updates"]))
        self.assertFalse(receipt["natural_task_gain_established"])

    def test_training_sources_and_annotation_masks_are_checked(self):
        with self.assertRaisesRegex(TokenTrainingFailure, "overlap"):
            fit_token_reader(TokenReader(8, 16), self.batch, self.batch.take([0]), steps=1, seed=2)
        bad = TokenBatch(**{**self.batch.__dict__, "evidence_supervision": None})
        with self.assertRaisesRegex(ValueError, "explicit"):
            bad.validate(8)
        no_source = TokenBatch(**{**self.batch.__dict__, "source_groups": ()})
        with self.assertRaisesRegex(TokenTrainingFailure, "source ownership"):
            fit_token_reader(TokenReader(8, 16), no_source, steps=1, seed=2)
        invalid = self.batch.evidence_targets.clone()
        invalid[0] *= 2
        bad = TokenBatch(**{**self.batch.__dict__, "evidence_targets": invalid})
        with self.assertRaisesRegex(ValueError, "normalized"):
            bad.validate(8)

    def test_intervention_updates_report_actual_exposures(self):
        natural, intervention = self.batch.take(list(range(24))), self.batch.take(list(range(24, 48)))
        _, receipt = fit_token_reader(TokenReader(8, 16), natural, steps=8, seed=11,
            batch_size=8, max_depth=2, counterfactual_train=intervention,
            counterfactual_fraction=.5, diagnostic_interval=8)
        self.assertEqual(receipt["actual_total_exposures"], 64)
        self.assertGreater(receipt["actual_training_exposures"], 0)
        self.assertGreater(receipt["actual_intervention_exposures"], 0)
        self.assertEqual(receipt["intervention_update_probability"], .5)
        self.assertEqual(receipt["actual_intervention_exposures"],
                         sum(row["exposures"] for row in receipt["updates"] if row["intervention"]))
        self.assertEqual(len(receipt["training_sources_sha256"]), 64)
        self.assertEqual(len(receipt["training_label_order_sha256"]), 64)

    def test_extreme_activation_gradients_stay_finite(self):
        for activation in (_sigmoid, _tanh):
            values = torch.tensor([-1e6, -100., 0., 100., 1e6], requires_grad=True)
            outputs = activation(values)
            outputs.sum().backward()
            self.assertTrue(torch.isfinite(outputs).all())
            self.assertTrue(torch.isfinite(values.grad).all())
            self.assertGreater(values.grad[2].item(), 0)

    def test_failed_fit_emits_partial_actual_cost_receipt(self):
        data = self.batch

        class InterruptedDataset:
            targets, source_groups = self.batch.targets, self.batch.source_groups
            calls = 0

            def validate(self, input_dim):
                pass

            def take(self, indices):
                self.calls += 1
                if self.calls == 3:
                    raise RuntimeError("simulated batch materialization failure")
                return data.take(indices)

        persisted = []
        with self.assertRaises(TokenTrainingFailure) as captured:
            fit_token_reader(TokenReader(8, 16), InterruptedDataset(), steps=8, seed=11, batch_size=48,
                             failure_receipt_fn=persisted.append)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0], captured.exception.receipt)
        self.assertEqual(persisted[0]["completed_steps"], 1)
        self.assertEqual(persisted[0]["actual_training_exposures"], 48)
        self.assertEqual(len(persisted[0]["updates"]), 1)
        self.assertGreater(persisted[0]["cpu_ns"], 0)
        self.assertTrue(persisted[0]["failed_attempt_time_included"])
        self.assertFalse(persisted[0]["final_evaluation_authorized"])


if __name__ == "__main__":
    unittest.main()
