"""Integration of frozen feedback prefix and one-review-per-generation fences.

SHADOW_ONLY: neither availability nor proposal lineage is owner authenticated.
"""
import unittest
from hashlib import sha256
from study import (Eligibility, Feedback, UpdateOpportunity,
                   cadence_gate, frozen_credit_from_prefix)


def d(x):
    return sha256(x.encode()).hexdigest()


GAPS = {"PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
        "VERIFY": 8, "ACT": 16, "LEARN": 16}


class ConvergedPrefixClockTests(unittest.TestCase):
    def test_future_bad_feedback_does_not_reopen_same_generation(self):
        actions = (Eligibility("act1", d("owner-declaration"), 1, (1.0, 0.0)),)
        prefix = (Feedback(d("prefix"), "act1", 3, (0.75, 0.0)),)
        future = (Feedback(d("invalid"), "not-an-action", 100, ("bad",)),)
        kw = dict(arm="routed", cutoff_sequence=5, decay=0.5, max_lag=4)
        frozen = frozen_credit_from_prefix(actions, prefix, **kw)
        self.assertEqual(frozen, frozen_credit_from_prefix(actions, prefix + future, **kw))
        self.assertEqual(frozen.authority, "DENY_ALL")

        # No second review for an already reviewed generation after clock elapses.
        events = (UpdateOpportunity("CTRL", 1, 7, True, True),
                  UpdateOpportunity("CTRL", 5, 7, True, True),
                  UpdateOpportunity("CTRL", 9, 7, True, True),
                  UpdateOpportunity("CTRL", 13, 8, True, True))
        results = cadence_gate(events, GAPS)
        self.assertEqual([v["status"] for v in results],
                         ["REVIEW_CANDIDATE", "NO_UPDATE", "NO_UPDATE", "REVIEW_CANDIDATE"])
        self.assertEqual({v["authority"] for v in results}, {"DENY_ALL"})

    def test_evidence_denial_then_first_review_with_frozen_feedback(self):
        actions = (Eligibility("act1", d("declared"), 1, (1.0,)),)
        credit = frozen_credit_from_prefix(actions, (), arm="routed", cutoff_sequence=2,
                                           decay=1.0, max_lag=1)
        self.assertEqual(credit.matched, 0)
        self.assertEqual(credit.deltas, (0.0,))
        # Evidence denial is not a review, so first qualified review is still possible.
        events = (UpdateOpportunity("MEM", 1, 1, False, False),
                  UpdateOpportunity("MEM", 2, 1, True, True),
                  UpdateOpportunity("MEM", 3, 1, True, True))
        self.assertEqual([x["status"] for x in cadence_gate(events, GAPS)],
                         ["NO_UPDATE", "REVIEW_CANDIDATE", "NO_UPDATE"])


if __name__ == "__main__":
    unittest.main()
