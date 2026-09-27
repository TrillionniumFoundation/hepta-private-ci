"""Actual PyTorch parameter updates on small fixtures, NOT Laya weight evidence."""
import copy
from dataclasses import replace
import time
import unittest

import torch
from torch import nn

from cell_head import (HeadBudget, HeadRejected, HeadRow, TrainingExpired,
                       digest, fit_head, restore_candidate, state_digest, validate_rows)


class HeadTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        with torch.random.fork_rng():
            torch.manual_seed(12)
            self.head = nn.Sequential(nn.LayerNorm(4), nn.Linear(4, 4), nn.GELU(), nn.Linear(4, 1)).eval()
        self.options = dict(scope="scope.training", objective=digest("objective"),
                            bundle=digest("base"), temperature=1.0, budget=HeadBudget(epochs=2),
                            deadline=time.monotonic() + 60)
        self.rows = tuple(HeadRow(f"row.{i}", f"group.{i}", i + 1, self.options["scope"],
                                 self.options["objective"], self.options["bundle"], digest(["source", i]),
                                 digest(["outcome", i]), ("abstain", "a", "b"),
                                 torch.tensor([[0., 1., 0., 0.], [1., 0., 0., 0.], [0., 0., 1., 0.]]),
                                 torch.tensor([0., 1., 0.])) for i in range(4))

    def fit(self, rows=None, **kwargs):
        return fit_head(self.head, self.rows if rows is None else rows, **(self.options | kwargs))

    def test_real_parameters_change_without_mutating_selected_or_dataset(self):
        before = state_digest(self.head)
        tensors = [r.features.clone() for r in self.rows]
        result = self.fit()
        self.assertEqual(result.disposition, "candidate")
        self.assertEqual(result.steps, 8)
        self.assertGreater(result.delta_norm, 0)
        self.assertEqual(state_digest(self.head), before)
        restored = restore_candidate(self.head, result, **{k: self.options[k] for k in ("bundle", "scope", "objective")})
        self.assertEqual(state_digest(restored), result.candidate_head_digest)
        for p, q in zip(self.head.parameters(), restored.parameters()):
            self.assertNotEqual(p.data_ptr(), q.data_ptr())
            self.assertIsNone(p.grad)
        for before_row, row in zip(tensors, self.rows):
            self.assertTrue(torch.equal(before_row, row.features))

    def test_no_data_and_insufficient_groups_are_no_change_without_steps(self):
        for rows in ((), self.rows[:1], tuple(replace(r, group_id="one") for r in self.rows)):
            with self.subTest(count=len(rows)):
                result = self.fit(rows)
                self.assertEqual((result.disposition, result.steps, result.payload), ("no_change", 0, None))
                self.assertEqual(result.baseline_head_digest, result.candidate_head_digest)

    def test_same_data_has_canonical_order_and_deterministic_candidate(self):
        first, second = self.fit(), self.fit(tuple(reversed(self.rows)))
        self.assertEqual(first.dataset_digest, second.dataset_digest)
        self.assertEqual(first.candidate_head_digest, second.candidate_head_digest)
        self.assertEqual(first.payload, second.payload)

    def test_step_tensor_and_invalid_budgets_reject_before_updates(self):
        before = state_digest(self.head)
        for budget in (HeadBudget(maximum_steps=1), HeadBudget(owned_tensor_bytes=1),
                       HeadBudget(epochs=True), HeadBudget(learning_rate=float("nan")),
                       HeadBudget(maximum_delta_norm=-1)):
            with self.subTest(budget=budget), self.assertRaises(HeadRejected):
                self.fit(budget=budget)
        self.assertEqual(state_digest(self.head), before)

    def test_l2_projection_bounds_actual_tensor_changes(self):
        result = self.fit(budget=HeadBudget(epochs=4, learning_rate=0.1, maximum_delta_norm=0.001))
        self.assertLessEqual(result.delta_norm, 0.001001)
        self.assertGreater(result.delta_norm, 0)

    def test_expired_or_regressing_clock_discards_candidate_not_selected_state(self):
        before = state_digest(self.head)
        with self.assertRaises(TrainingExpired):
            self.fit(deadline=0)
        ticks = iter([0, 0, 0, 0, 0, 0, 2])
        with self.assertRaises(TrainingExpired) as caught:
            self.fit(deadline=1, clock=lambda: next(ticks, 2))
        self.assertGreater(caught.exception.steps, 0)
        ticks = iter([1., 1., .9])
        with self.assertRaises(TrainingExpired):
            self.fit(deadline=2, clock=lambda: next(ticks, .9))
        self.assertEqual(state_digest(self.head), before)

    def test_scope_objective_bundle_source_and_outcome_reject_substitution(self):
        for fields in ({"scope_id": "other"}, {"objective_digest": digest("other")},
                       {"bundle_digest": digest("other")}, {"source_digest": "0" * 64},
                       {"outcome_digest": "0" * 64}, {"observed_at_ms": True}):
            with self.subTest(fields=fields), self.assertRaises(HeadRejected):
                self.fit((replace(self.rows[0], **fields), *self.rows[1:]))

    def test_duplicate_row_or_outcome_cannot_manufacture_support(self):
        for fields in ({"row_id": self.rows[0].row_id}, {"outcome_digest": self.rows[0].outcome_digest}):
            with self.subTest(fields=fields), self.assertRaises(HeadRejected):
                self.fit((self.rows[0], replace(self.rows[1], **fields)))

    def test_complete_action_order_and_tensor_contract_are_not_advisory(self):
        for fields in ({"option_ids": ("a", "b", "abstain")},
                       {"option_ids": ("abstain", "b", "a")},
                       {"features": torch.zeros((3, 5))}, {"features": torch.zeros((3, 4), dtype=torch.float64)},
                       {"target": torch.tensor([.1, .1, .1])}, {"target": torch.tensor([float("nan"), 0., 1.])},
                       {"target": torch.tensor([0., 1., 0.], requires_grad=True)}):
            with self.subTest(fields=fields), self.assertRaises(HeadRejected):
                self.fit((replace(self.rows[0], **fields), *self.rows[1:]))

    def test_unsupported_executable_head_is_rejected(self):
        self.head.train()
        with self.assertRaises(HeadRejected):
            self.fit()
        self.head = nn.Sequential(nn.Linear(4, 1)).eval()
        with self.assertRaises(HeadRejected):
            self.fit()

    def test_restore_rejects_tampering_and_wrong_base_without_mutation(self):
        result = self.fit()
        before = state_digest(self.head)
        for fields in ({"payload": result.payload[:-1] + b"X"}, {"base_bundle_digest": digest("other")},
                       {"scope_id": "other"}, {"objective_digest": digest("other")},
                       {"baseline_head_digest": digest("other")}, {"candidate_head_digest": digest("other")}):
            with self.subTest(fields=fields), self.assertRaises(HeadRejected):
                restore_candidate(self.head, replace(result, **fields), **{k: self.options[k] for k in ("bundle", "scope", "objective")})
        self.assertEqual(state_digest(self.head), before)

    def test_dataset_digest_binds_targets_and_features_not_only_row_labels(self):
        options = (4, self.options["scope"], self.options["objective"], self.options["bundle"])
        before = validate_rows(self.rows, *options)
        changed = (replace(self.rows[0], target=torch.tensor([1., 0., 0.])), *self.rows[1:])
        self.assertNotEqual(validate_rows(changed, *options), before)
        changed = (replace(self.rows[0], features=self.rows[0].features + 1), *self.rows[1:])
        self.assertNotEqual(validate_rows(changed, *options), before)

    def test_no_hidden_random_seed_or_selected_optimizer_state_mutation(self):
        rng = torch.get_rng_state().clone()
        self.fit()
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))

    def test_uniform_identical_choices_make_zero_delta_no_change(self):
        rows = tuple(replace(row, option_ids=("abstain", "a"), features=torch.zeros(2, 4),
                             target=torch.tensor([0.5, 0.5])) for row in self.rows)
        result = self.fit(rows)
        self.assertEqual((result.disposition, result.payload, result.delta_norm), ("no_change", None, 0.0))
        self.assertGreater(result.steps, 0)  # Computation happened even without an update.

    def test_gradient_matches_independent_softmax_oracle(self):
        candidate = copy.deepcopy(self.head)
        features, target = self.rows[0].features, self.rows[0].target
        logits = candidate(features).squeeze(-1)
        p = torch.softmax(logits.detach(), dim=-1)
        # d CE / d logits = prediction - independent target.
        logits.backward(p - target)
        reference = copy.deepcopy(self.head)
        loss = -(target * torch.log_softmax(reference(features).squeeze(-1), dim=-1)).sum()
        loss.backward()
        for a, b in zip(candidate.parameters(), reference.parameters()):
            torch.testing.assert_close(a.grad, b.grad, rtol=1e-5, atol=1e-7)

    def test_training_profile_binds_optimizer_and_temperature(self):
        a = self.fit()
        b = self.fit(budget=HeadBudget(learning_rate=0.02))
        c = self.fit(temperature=2.0)
        self.assertEqual(len({a.training_profile_digest, b.training_profile_digest, c.training_profile_digest}), 3)

    def test_nonrow_is_rejected_without_attribute_dispatch(self):
        with self.assertRaises(HeadRejected):
            self.fit((None,))


if __name__ == "__main__":
    unittest.main()
