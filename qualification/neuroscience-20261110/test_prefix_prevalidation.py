"""Frozen training view must not depend on post-cutoff feedback validation."""
from hashlib import sha256
from dataclasses import asdict
import unittest

from study import (
    ContractError, Eligibility, Feedback, frozen_credit_from_prefix,
    frozen_credit_view, time_aligned_credit,
)

def sha(s):
    return sha256(s.encode()).hexdigest()

ACTIONS = (
    Eligibility("a1", sha("src1"), 1, (1.0, 0.0)),
    Eligibility("a2", sha("src2"), 2, (0.0, 1.0)),
)
KW = {"arm": "routed", "cutoff_sequence": 5, "decay": 0.5, "max_lag": 4}
PREFIX = (Feedback(sha("observed"), "a1", 3, (0.5, 0.0)),)

class PrefixPrevalidationTests(unittest.TestCase):
    def frozen(self, feedback):
        return frozen_credit_from_prefix(ACTIONS, feedback, **KW)

    def test_valid_prefix_matches_full_forensic_audit(self):
        self.assertEqual(self.frozen(PREFIX),
                         frozen_credit_view(time_aligned_credit(ACTIONS, PREFIX, **KW)))
        self.assertEqual(self.frozen(PREFIX).authority, "DENY_ALL")

    def test_future_unknown_action_cannot_gate_frozen_selection(self):
        future = Feedback(sha("orphan"), "not_an_action", 8, (0.5, 0.5))
        with self.assertRaises(ContractError):
            time_aligned_credit(ACTIONS, PREFIX + (future,), **KW)
        self.assertEqual(self.frozen(PREFIX), self.frozen(PREFIX + (future,)))

    def test_future_duplicate_or_malformed_modulator_cannot_gate_selection(self):
        suffix = (
            Feedback(sha("observed"), "a2", 7, (0.0, 1.0)),
            Feedback(sha("other"), "a2", 9, ("ill_formed",)),
        )
        with self.assertRaises(ContractError):
            time_aligned_credit(ACTIONS, PREFIX + suffix, **KW)
        self.assertEqual(self.frozen(PREFIX), self.frozen(PREFIX + suffix))

    def test_unobserved_bad_feedback_still_fails_closed(self):
        malformed = Feedback(sha("bad-now"), "unknown", 4, (0.0, 1.0))
        with self.assertRaises(ContractError):
            self.frozen(PREFIX + (malformed,))

    def test_non_integer_availability_cannot_be_misclassified_future(self):
        bad = Feedback(sha("wrong-time"), "a2", "9", (1.0, 0.0))
        with self.assertRaises(ContractError):
            self.frozen(PREFIX + (bad,))

    def test_frozen_fields_exclude_future_forensic_metadata(self):
        obj = asdict(self.frozen(PREFIX))
        for field in ("transcript_digest", "future_withheld", "unobserved_action_count"):
            self.assertNotIn(field, obj)

if __name__ == "__main__":
    unittest.main()
