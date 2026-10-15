"""Mechanics of a controlled program search, not pretrained-model efficacy."""

from fractions import Fraction
import unittest
from unittest.mock import patch

import torch

from system2_ablation import model_digest
from system2_verified_search import (
    ExactLabels,
    features,
    search,
    successors,
    train_critic,
    verify,
)


class VerifiedSearchTests(unittest.TestCase):
    def test_independent_fractional_proof_and_reused_operand_rejection(self):
        proof = ["n3", "n0", "n1", "n2", "/", "-", "/"]
        self.assertTrue(verify((1, 3, 4, 6), 24, proof))
        self.assertFalse(verify((1, 3, 4, 6), 25, proof))
        self.assertFalse(
            verify((1, 3, 4, 6), 24, ["n3", "n0", "n0", "n2", "/", "-", "/"])
        )
        self.assertFalse(verify((1, 3, 4, 6), 24, ['__import__("os")'] * 7))

    def test_exact_labels_solvable_and_impossible(self):
        labeler = ExactLabels()
        self.assertTrue(labeler.solve(tuple(map(Fraction, (1, 3, 4, 6))), 24))
        self.assertFalse(labeler.solve(tuple(map(Fraction, (1, 1, 1, 1))), 24))

    def test_search_uses_runtime_verifier_not_reachability_oracle(self):
        with patch.object(
            ExactLabels, "_solve", side_effect=AssertionError("oracle leakage")
        ):
            result = search((1, 3, 4, 6), 24, "breadth_first", 8192)
        self.assertTrue(result["found"])
        self.assertTrue(verify((1, 3, 4, 6), 24, result["proof"]))

    def test_budget_exhaustion_is_not_proof_of_impossibility(self):
        result = search((1, 3, 4, 6), 24, "breadth_first", 1)
        self.assertFalse(result["found"])
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(result["costs"]["popped_states"], 1)
        self.assertGreater(result["costs"]["generated_successors"], 0)

    def test_state_features_are_goal_and_state_conditioned(self):
        values = tuple(map(Fraction, (1, 3, 4, 6)))
        self.assertEqual(len(features(values, 24)), 12)
        self.assertNotEqual(features(values, 24), features(values, 10))
        self.assertNotEqual(
            features(values, 24), features(tuple(map(Fraction, (1, 1, 1, 1))), 24)
        )

    def test_legal_successors_preserve_operand_proofs(self):
        terms = tuple(
            (Fraction(v), ("n" + str(i),)) for i, v in enumerate((1, 3, 4, 6))
        )
        for child in successors(terms):
            leaves = [
                token for _, proof in child for token in proof if token.startswith("n")
            ]
            self.assertEqual(sorted(leaves), ["n0", "n1", "n2", "n3"])
            self.assertEqual(len(child), 3)

    def test_real_training_then_frozen_inference(self):
        model, receipt = train_critic([(1, 3, 4, 6), (1, 1, 1, 1)], steps=4)
        self.assertNotEqual(receipt["before"], receipt["after"])
        self.assertFalse(any(p.requires_grad for p in model.parameters()))
        before = model_digest(model)
        result = search((1, 2, 3, 4), 24, "ndu_value", 32, model)
        self.assertEqual(before, model_digest(model))
        self.assertLessEqual(result["costs"]["popped_states"], 32)

    def test_shuffled_control_same_examples_initialization_and_update_count(self):
        tasks = [(1, 3, 4, 6), (1, 1, 1, 1)]
        _, a = train_critic(tasks, steps=4)
        _, b = train_critic(tasks, shuffled=True, steps=4)
        self.assertEqual(a["before"], b["before"])
        self.assertEqual(a["examples"], b["examples"])
        self.assertEqual(a["positives"], b["positives"])
        self.assertEqual(a["state_keys"], b["state_keys"])
        self.assertEqual(a["steps"], b["steps"])

    def test_invalid_budget_and_nan_critic_rejected(self):
        for budget in (0, True, 100000):
            with self.assertRaises(ValueError):
                search((1, 2, 3, 4), 24, "value_search", budget)

        class Bad(torch.nn.Module):
            def forward(self, x):
                return torch.full((len(x), 1), float("nan"))

        with self.assertRaises(ValueError):
            search((1, 2, 3, 4), 24, "value_search", 32, Bad())


if __name__ == "__main__":
    unittest.main()
