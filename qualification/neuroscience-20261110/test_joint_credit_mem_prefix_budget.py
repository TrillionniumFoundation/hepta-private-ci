"""Joint cutoff/budget invariants for two independent shadow selectors.

These self-declared time sequences are NOT Owner-attested. These tests verify
reference contracts only, not learning gain, production admission or release.
"""
import unittest
from hashlib import sha256
from itertools import chain, repeat

from study import (
    ContractError, Eligibility, Feedback, MemoryRecord,
    frozen_credit_from_prefix, frozen_replay_from_prefix,
)


def sha(label):
    return sha256(label.encode("utf-8")).hexdigest()


class JointCreditMemoryPrefixTests(unittest.TestCase):
    def setUp(self):
        self.action = Eligibility("a1", sha("action-source"), 1, (0.5,))
        self.observed_feedback = Feedback(sha("observed-feedback"), "a1", 4, (0.8,))
        self.invalid_future_feedback = Feedback("BAD_DIGEST", "a1", 15, (100.0,))
        self.credit_kw = dict(arm="routed", cutoff_sequence=10,
                              decay=1.0, max_lag=10)
        self.mem = [
            MemoryRecord("fact", "fact", "q", sha("f"), 1,
                         logical_id="fact-identity"),
            MemoryRecord("episode", "episode", "q", sha("e"), 2),
            MemoryRecord("skill", "skill", "q", sha("s"), 3),
            MemoryRecord("recovery", "recovery", "q", sha("r"), 4),
        ]
        self.invalid_future_memory = MemoryRecord(
            "episode", "episode", "q", "BAD_DIGEST", 20)

    def credit(self, rows):
        return frozen_credit_from_prefix(
            [self.action], rows, **self.credit_kw)

    def replay(self, rows, seed, cutoff=10, policy="stratified"):
        return frozen_replay_from_prefix(
            rows, policy=policy, query_key="q", now_sequence=cutoff,
            max_items=1, seed=seed)

    def test_matching_credit_and_rotated_replay_share_a_causal_cutoff(self):
        baseline_credit = self.credit([self.observed_feedback])
        extended_credit = self.credit([
            self.observed_feedback, self.invalid_future_feedback])
        self.assertEqual(baseline_credit, extended_credit)
        self.assertEqual(baseline_credit.authority, "DENY_ALL")
        self.assertEqual(baseline_credit.matched, 1)
        self.assertEqual(baseline_credit.deltas, (0.4,))
        outcomes = set()
        for i in range(128):
            seed = f"trial-owner-proposed:{i}"
            a = self.replay(self.mem, seed)
            b = self.replay(self.mem + [self.invalid_future_memory], seed)
            self.assertEqual(a, b)
            outcomes.add(a[0])
        self.assertEqual(outcomes, {"fact", "episode", "skill", "recovery"})

    def test_visible_deletion_is_sticky_without_changing_past_credit(self):
        removed = MemoryRecord(
            "fact-delete", "fact", "q", sha("f-delete"), 8,
            tombstoned=True, logical_id="fact-identity")
        revival = MemoryRecord(
            "fact-revive", "fact", "q", sha("f-revive"), 12,
            logical_id="fact-identity")
        base_credit = self.credit([self.observed_feedback])
        for i in range(64):
            seed = f"trial-owner-proposed:{i}"
            a = self.replay(self.mem + [removed], seed)
            b = self.replay(self.mem + [removed, revival], seed)
            self.assertEqual(a, b)
            self.assertNotEqual(a[0], "fact")
        self.assertEqual(self.credit([
            self.observed_feedback, self.invalid_future_feedback]), base_credit)

    def test_both_raw_future_iterators_fail_at_first_over_budget_item(self):
        seen_feedback = 0
        seen_memory = 0

        def feedback():
            nonlocal seen_feedback
            for item in repeat(self.invalid_future_feedback, 65_538):
                seen_feedback += 1
                yield item

        def memory():
            nonlocal seen_memory
            for item in repeat(self.invalid_future_memory, 65_538):
                seen_memory += 1
                yield item

        with self.assertRaisesRegex(ContractError, "raw feedback exceeds size limit"):
            self.credit(feedback())
        with self.assertRaisesRegex(ContractError, "frozen replay input exceeds size limit"):
            self.replay(memory(), "s")
        self.assertEqual((seen_feedback, seen_memory), (65_537, 65_537))

    def test_shared_input_budget_edge_is_admitted_without_future_leak(self):
        credit = self.credit(chain(
            [self.observed_feedback],
            repeat(self.invalid_future_feedback, 65_535),
        ))
        replay = self.replay(
            chain(self.mem,
                  repeat(self.invalid_future_memory, 65_532)),
            "same-declared-seed",
        )
        self.assertEqual(credit.matched, 1)
        self.assertEqual(credit.deltas, (0.4,))
        self.assertIn(replay[0], {"fact", "episode", "skill", "recovery"})


if __name__ == "__main__":
    unittest.main()
