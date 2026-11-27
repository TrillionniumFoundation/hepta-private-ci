"""Shadow-only fail-closed projection: no full-audit hindsight in candidate view."""
import unittest
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from study import (
    ContractError, Eligibility, Feedback, frozen_credit_view, time_aligned_credit,
)

def digest(s):
    return sha256(s.encode("utf-8")).hexdigest()

ACTIONS = (
    Eligibility("a1", digest("source1"), 1, (1.0, 0.0)),
    Eligibility("a2", digest("source2"), 2, (0.0, 1.0)),
)

def audit(feedback, arm="routed"):
    return time_aligned_credit(
        ACTIONS, feedback, arm=arm, cutoff_sequence=5, decay=0.5, max_lag=4,
    )

class FrozenCreditViewTests(unittest.TestCase):
    def test_future_audit_counters_cannot_enter_frozen_selection_view(self):
        before = audit(())
        later = audit((Feedback(digest("future"), "a1", 6, (1.0, 0.0)),))
        self.assertNotEqual(before.unobserved_action_count,
                            later.unobserved_action_count)
        self.assertNotEqual(before.transcript_digest, later.transcript_digest)
        self.assertNotEqual(before.future_withheld, later.future_withheld)
        frozen = asdict(frozen_credit_view(before))
        self.assertEqual(frozen, asdict(frozen_credit_view(later)))
        self.assertNotIn("unobserved_action_count", frozen)
        self.assertNotIn("future_withheld", frozen)
        self.assertNotIn("transcript_digest", frozen)
        self.assertEqual(frozen["authority"], "DENY_ALL")

    def test_future_content_mutation_does_not_change_frozen_view(self):
        base = (Feedback(digest("observed"), "a1", 3, (0.5, 0.0)),)
        later1 = base + (Feedback(digest("later1"), "a2", 7, (1.0, -1.0)),)
        later2 = base + (Feedback(digest("later2"), "a2", 8, (-1.0, 0.5)),)
        self.assertEqual(frozen_credit_view(audit(later1)),
                         frozen_credit_view(audit(later2)))
        self.assertNotEqual(audit(later1).transcript_digest,
                            audit(later2).transcript_digest)

    def test_32_future_suffix_mutations_are_prefix_invariant(self):
        reference = frozen_credit_view(audit(()))
        for i in range(32):
            with self.subTest(i=i):
                suffix = (
                    Feedback(digest(f"future1:{i}"), "a1", 6 + i,
                             (1.0 if i % 2 else -1.0, 0.25)),
                    Feedback(digest(f"future2:{i}"), "a2", 9 + i,
                             (0.0, -1.0 if i % 3 else 1.0)),
                )
                self.assertEqual(frozen_credit_view(audit(suffix)), reference)

    def test_observed_zero_and_absent_remain_distinct(self):
        absent = frozen_credit_view(audit(()))
        observed = frozen_credit_view(audit(
            (Feedback(digest("zero"), "a1", 4, (0.0, 0.0)),)
        ))
        self.assertEqual(absent.deltas, observed.deltas)
        self.assertNotEqual(absent.matched, observed.matched)
        self.assertNotEqual(absent.causal_training_digest,
                            observed.causal_training_digest)

    def test_all_ablation_arms_keep_frozen_authority(self):
        later = (Feedback(digest("future"), "a1", 6, (1.0, -1.0)),)
        for arm in ("routed", "shuffled", "scalar", "no_eligibility"):
            with self.subTest(arm=arm):
                f = frozen_credit_view(audit(later, arm))
                self.assertEqual(f.authority, "DENY_ALL")
                self.assertEqual(f.qualification, "SHADOW_ONLY")
                self.assertEqual(f.matched, 0)
                self.assertEqual(f.deltas, (0.0, 0.0))

    def test_projection_is_frozen_and_type_checked(self):
        obj = frozen_credit_view(audit(()))
        with self.assertRaises(FrozenInstanceError):
            obj.matched = 123
        with self.assertRaises(ContractError):
            frozen_credit_view({"matched": 0})

if __name__ == "__main__":
    unittest.main()
