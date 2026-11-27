"""Adversarial sparse/delayed missing feedback contract, shadow-only."""
import unittest
from hashlib import sha256
from dataclasses import replace
from study import (
    ContractError, Eligibility, Feedback, time_aligned_credit
)

def digest(label):
    return sha256(label.encode("utf-8")).hexdigest()

def actions():
    return (
        Eligibility("action:1", digest("source:1"), 1, (1.0, 0.0)),
        Eligibility("action:2", digest("source:2"), 2, (0.0, 1.0)),
    )

def compute(feedback, *, arm="routed", actions_arg=None):
    return time_aligned_credit(
        actions() if actions_arg is None else actions_arg,
        feedback, arm=arm, cutoff_sequence=5, decay=0.5,
        max_lag=4,
    )

class SparseNoFeedbackTests(unittest.TestCase):
    def test_no_feedback_is_valid_missing_not_success_for_all_arms(self):
        for arm in ("routed", "shuffled", "scalar", "no_eligibility"):
            with self.subTest(arm=arm):
                result = compute((), arm=arm)
                self.assertEqual(result.deltas, (0.0, 0.0))
                self.assertEqual((result.matched, result.expired, result.future_withheld), (0, 0, 0))
                self.assertEqual(result.unobserved_action_count, 2)
                self.assertEqual(result.authority, "DENY_ALL")

    def test_observed_zero_is_not_absent_feedback(self):
        absent = compute(())
        zero = compute((Feedback(digest("receipt:zero"), "action:1", 4, (0.0, 0.0)),))
        self.assertEqual(zero.deltas, absent.deltas)
        self.assertEqual(zero.matched, 1)
        self.assertEqual(zero.unobserved_action_count, 1)
        self.assertNotEqual(zero.transcript_digest, absent.transcript_digest)
        self.assertNotEqual(zero.causal_training_digest, absent.causal_training_digest)

    def test_future_receipt_is_forensic_only_not_frozen_causal_feature(self):
        absent = compute(())
        future = compute((Feedback(digest("receipt:future"), "action:1", 6, (1.0, 0.0)),))
        self.assertEqual(future.deltas, absent.deltas)
        self.assertEqual(future.matched, 0)
        self.assertEqual(future.future_withheld, 1)
        self.assertEqual(future.causal_training_digest, absent.causal_training_digest)
        self.assertNotEqual(future.transcript_digest, absent.transcript_digest)

    def test_empty_feedback_cannot_bypass_invalid_actions(self):
        with self.assertRaises(ContractError):
            compute((), actions_arg=())
        with self.assertRaises(ContractError):
            compute((), actions_arg=(replace(actions()[0], split="evaluation"),))
        with self.assertRaises(ContractError):
            compute((), actions_arg=(replace(actions()[0], sequence=6),))

    def test_receipt_without_matching_action_is_not_absence(self):
        with self.assertRaises(ContractError):
            compute((Feedback(digest("receipt:unknown"), "unknown", 4, (0.0, 0.0)),))

if __name__ == "__main__":
    unittest.main()
