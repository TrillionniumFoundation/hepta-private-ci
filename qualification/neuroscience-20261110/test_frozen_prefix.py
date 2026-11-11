"""Frozen-prefix research preflight; no real model or owner evidence."""
import unittest
from dataclasses import fields, replace
from hashlib import sha256

from frozen_prefix import frozen_prefix_proposal, FrozenPrefixProposal
from study import ContractError, Eligibility, Feedback, time_aligned_credit


def sha(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def actions():
    return (
        Eligibility("a1", sha("source1"), 1, (1.0, 0.0)),
        Eligibility("a2", sha("source2"), 2, (0.0, 1.0)),
    )


def feedback():
    return (
        Feedback(sha("receipt1"), "a1", 4, (1.0, 0.0)),
        Feedback(sha("receipt2"), "a2", 5, (0.0, 1.0)),
    )


def frozen(cutoff=2, available=()):
    return frozen_prefix_proposal(
        actions(), available, arm="routed", cutoff_sequence=cutoff,
        decay=1.0, max_lag=8,
    )


class FrozenPrefixTests(unittest.TestCase):
    def test_zero_feedback_is_no_update_and_deny_all(self):
        p = frozen()
        self.assertIsInstance(p, FrozenPrefixProposal)
        self.assertEqual((p.group_deltas, p.matched_feedback_count,
                          p.expired_feedback_count), ((0.0, 0.0), 0, 0))
        self.assertEqual(p.authority, "DENY_ALL")
        self.assertEqual(p.qualification, "UNATTESTED_PREFIX_ONLY")

    def test_strict_frozen_input_rejects_every_future_receipt(self):
        with self.assertRaisesRegex(ContractError, "post-cutoff"):
            frozen(available=feedback())
        with self.assertRaisesRegex(ContractError, "post-cutoff"):
            frozen(available=[replace(feedback()[0],
                                     receipt_digest=sha("different-label"))])
        with self.assertRaisesRegex(ContractError, "post-cutoff"):
            frozen(available=[replace(feedback()[0], available_sequence=True)])

    def test_causal_key_matches_full_audit_without_exposing_future(self):
        blind = frozen()
        audit = time_aligned_credit(
            actions(), feedback(), arm="routed", cutoff_sequence=2,
            decay=1.0, max_lag=8,
        )
        self.assertEqual(blind.causal_training_digest,
                         audit.causal_training_digest)
        self.assertEqual(blind.group_deltas, audit.deltas)
        self.assertEqual(audit.future_withheld, 2)

    def test_complete_visible_prefix_matches_full_reference(self):
        p = frozen(cutoff=5, available=feedback())
        full = time_aligned_credit(
            actions(), feedback(), arm="routed", cutoff_sequence=5,
            decay=1.0, max_lag=8,
        )
        self.assertEqual(p.group_deltas, full.deltas)
        self.assertEqual(p.causal_training_digest, full.causal_training_digest)
        self.assertEqual(p.matched_feedback_count, 2)

    def test_expired_visible_feedback_still_audited(self):
        p = frozen_prefix_proposal(
            actions(), (feedback()[0],), arm="routed", cutoff_sequence=4,
            decay=1.0, max_lag=2,
        )
        self.assertEqual(p.expired_feedback_count, 1)
        self.assertEqual(p.group_deltas, (0.0, 0.0))

    def test_proposal_cannot_export_full_transcript_or_future_count(self):
        names = {field.name for field in fields(FrozenPrefixProposal)}
        self.assertNotIn("transcript_digest", names)
        self.assertNotIn("future_withheld", names)
        self.assertNotIn("withheld_future_feedback_count", names)
        self.assertNotIn("complete_input_digest", names)

    def test_prefix_tamper_and_duplicate_fail_closed(self):
        with self.assertRaises(ContractError):
            frozen(cutoff=5, available=(feedback()[0], feedback()[0]))
        with self.assertRaises(ContractError):
            frozen(cutoff=5, available=(replace(feedback()[0], action_id="x"),))
        with self.assertRaises(ContractError):
            frozen(cutoff=5, available=(replace(feedback()[0],
                                               available_sequence=0),))
        with self.assertRaises(ContractError):
            frozen_prefix_proposal([], (), arm="routed", cutoff_sequence=2,
                                   decay=1.0, max_lag=8)

    def test_invalid_cutoff_rejected_before_shadow_math(self):
        for invalid in (True, -1, 1.2, "2"):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                frozen(cutoff=invalid)


if __name__ == "__main__":
    unittest.main()
