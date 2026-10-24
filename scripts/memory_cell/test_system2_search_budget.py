"""Terminal-verifier and fixed-budget controls; no language-model efficacy claim."""

import itertools
import unittest
from unittest.mock import patch
from fractions import Fraction

import torch
from torch import nn

from system2_verified_search import (
    ARMS,
    ExactLabels,
    digest,
    search,
    successors,
    verify,
)
from system2_search_budget import task_groups


class NonterminalCritic(nn.Module):
    def forward(self, x):
        if bool((x[:, 4] == 0.25).any()):
            raise AssertionError("known terminal sent to learned critic")
        return torch.zeros(len(x), 1)


class SearchBudgetTests(unittest.TestCase):
    def test_eager_verifies_proofs_without_terminal_critic_or_oracle(self):
        with patch.object(
            ExactLabels, "_solve", side_effect=AssertionError("oracle leakage")
        ):
            row = search(
                (1, 2, 3, 4),
                24,
                "value_search",
                8192,
                NonterminalCritic(),
                terminal_policy="eager",
            )
        self.assertTrue(row["found"])
        self.assertTrue(verify((1, 2, 3, 4), 24, row["proof"]))
        self.assertGreater(row["costs"]["verifier_calls"], 0)

    def test_deferred_default_is_unchanged(self):
        for arm in ("greedy", "breadth_first", "heuristic_search", "flat_ndu"):
            a = search((1, 3, 4, 6), 24, arm, 64)
            b = search(
                (1, 3, 4, 6),
                24,
                arm,
                64,
                terminal_policy="deferred",
                successor_limit=None,
            )
            self.assertEqual(
                {k: v for k, v in a.items() if k != "seconds"},
                {k: v for k, v in b.items() if k != "seconds"},
            )

    def test_common_successor_cap_counts_real_yields_including_duplicates(self):
        for policy, arm in itertools.product(("deferred", "eager"), ARMS):
            yielded = []

            def observed(terms):
                for child in successors(terms):
                    yielded.append(child)
                    yield child

            with patch("system2_verified_search.successors", side_effect=observed):
                row = search(
                    (1, 2, 3, 4),
                    24,
                    arm,
                    8192,
                    NonterminalCritic(),
                    terminal_policy=policy,
                    successor_limit=5,
                )
            self.assertEqual(len(yielded), 5)
            self.assertEqual(row["costs"]["generated_successors"], 5)
            self.assertFalse(row["found"])
            self.assertTrue(row["budget_exhausted"])

    def test_eager_rejects_invalid_proof_even_when_reported_value_is_goal(self):
        invented = ((Fraction(24), ("n0",) * 7),)
        with patch("system2_verified_search.successors", return_value=iter([invented])):
            row = search((1, 2, 3, 4), 24, "breadth_first", 16, terminal_policy="eager")
        self.assertFalse(row["found"])
        self.assertEqual(row["costs"]["verifier_calls"], 1)

    def test_eager_discards_known_wrong_leaves_without_critic(self):
        row = search(
            (1, 1, 1, 1),
            24,
            "ndu_value",
            8192,
            NonterminalCritic(),
            terminal_policy="eager",
        )
        self.assertFalse(row["found"])
        self.assertGreater(row["costs"]["verifier_calls"], 0)
        self.assertNotIn("solvable", row)

    def test_unregistered_budgets_and_terminal_rules_rejected(self):
        for limit in (0, -1, True, 65537, 1.5):
            with self.assertRaises(ValueError):
                search((1, 2, 3, 4), 24, "breadth_first", 64, successor_limit=limit)
        with self.assertRaises(ValueError):
            search((1, 2, 3, 4), 24, "breadth_first", 64, terminal_policy="oracle")

    def test_next_tasks_are_hash_selected_not_selected_by_solvability(self):
        catalogue = sorted(
            itertools.combinations_with_replacement(range(1, 10), 4),
            key=lambda n: digest(("verified-search-v1", n)),
        )
        parent = dict(training=catalogue[:12], evaluation=catalogue[12:36])
        groups = task_groups(parent)
        self.assertEqual(groups["next_hash_slice"], catalogue[36:60])
        self.assertFalse(set(groups["next_hash_slice"]) & set(catalogue[:36]))
        parent["training"] = list(reversed(parent["training"]))
        with self.assertRaises(ValueError):
            task_groups(parent)

    def test_more_generation_cannot_invalidate_a_returned_proof(self):
        numbers = (1, 3, 4, 6)
        small = search(
            numbers,
            24,
            "heuristic_search",
            8192,
            terminal_policy="eager",
            successor_limit=256,
        )
        large = search(
            numbers,
            24,
            "heuristic_search",
            8192,
            terminal_policy="eager",
            successor_limit=1024,
        )
        if small["found"]:
            self.assertTrue(verify(numbers, 24, small["proof"]))
        if large["found"]:
            self.assertTrue(verify(numbers, 24, large["proof"]))
        self.assertLessEqual(small["costs"]["generated_successors"], 256)
        self.assertLessEqual(large["costs"]["generated_successors"], 1024)


if __name__ == "__main__":
    unittest.main()
