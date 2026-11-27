"""Bound raw frozen-credit scans even for entirely future feedback.

Reference-only: no owner time attestation, independent evaluator, effects, or
model adoption. The unchanged in-window credit policy is independently tested.
"""
import unittest
from hashlib import sha256
from itertools import chain, repeat

from study import ContractError, Eligibility, Feedback, frozen_credit_from_prefix


def digest(label):
    return sha256(label.encode("utf-8")).hexdigest()


class FrozenCreditRawBudgetTests(unittest.TestCase):
    def setUp(self):
        self.action = Eligibility("action-1", digest("source-1"), 1, (0.5,))
        self.future = Feedback(digest("future-1"), "action-1", 11, (0.25,))
        self.past = Feedback(digest("past-1"), "action-1", 2, (0.8,))
        self.kw = dict(arm="routed", cutoff_sequence=10, decay=1.0,
                       max_lag=10)

    def test_maximum_raw_future_suffix_is_bounded_and_causally_ignored(self):
        baseline = frozen_credit_from_prefix([self.action], [], **self.kw)
        at_budget = frozen_credit_from_prefix(
            [self.action], repeat(self.future, 65_536), **self.kw)
        self.assertEqual(at_budget, baseline)
        self.assertEqual(at_budget.matched, 0)
        self.assertEqual(at_budget.deltas, (0.0,))
        self.assertEqual(at_budget.authority, "DENY_ALL")

    def test_one_over_raw_limit_is_a_resource_refusal_not_an_adoption(self):
        yielded = 0

        def raw():
            nonlocal yielded
            for _ in range(65_538):
                yielded += 1
                yield self.future

        with self.assertRaisesRegex(ContractError, "raw feedback exceeds size limit"):
            frozen_credit_from_prefix([self.action], raw(), **self.kw)
        # Do not exhaust arbitrary user-controlled iterables past the first
        # over-budget item. This is a bounded scan even when all rows are future.
        self.assertEqual(yielded, 65_537)

    def test_observed_feedback_remains_credited_with_maximum_future_suffix(self):
        baseline = frozen_credit_from_prefix(
            [self.action], [self.past], **self.kw)
        bounded = frozen_credit_from_prefix(
            [self.action], chain([self.past], repeat(self.future, 65_535)),
            **self.kw)
        self.assertEqual(bounded, baseline)
        self.assertEqual(bounded.matched, 1)
        self.assertAlmostEqual(bounded.deltas[0], 0.4)

    def test_just_over_budget_after_valid_prefix_fails_closed(self):
        with self.assertRaises(ContractError):
            frozen_credit_from_prefix(
                [self.action], chain([self.past], repeat(self.future, 65_536)),
                **self.kw)


if __name__ == "__main__":
    unittest.main()
