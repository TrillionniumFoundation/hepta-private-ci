"""Fail-closed generation identity regression tests, qualification-only."""
import unittest

from study import ContractError, UpdateOpportunity, cadence_gate


GAPS = {
    "PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
    "VERIFY": 8, "ACT": 16, "LEARN": 16,
}


class GenerationClockTests(unittest.TestCase):
    def test_rollback_after_review_cannot_be_reviewed(self):
        events = [
            UpdateOpportunity("PERC", 1, 5, True, True),
            UpdateOpportunity("PERC", 17, 4, True, True),
        ]
        with self.assertRaisesRegex(ContractError, "generation regression"):
            cadence_gate(events, GAPS)

    def test_rollback_after_denied_opportunity_cannot_be_replayed(self):
        events = [
            UpdateOpportunity("CTRL", 1, 8, False, False),
            UpdateOpportunity("CTRL", 5, 7, True, True),
        ]
        with self.assertRaisesRegex(ContractError, "generation regression"):
            cadence_gate(events, GAPS)

    def test_rollback_on_clock_denied_intermediate_is_still_rejected(self):
        events = [
            UpdateOpportunity("PERC", 1, 8, True, True),
            UpdateOpportunity("PERC", 2, 9, False, True),
            UpdateOpportunity("PERC", 17, 8, True, True),
        ]
        with self.assertRaisesRegex(ContractError, "generation regression"):
            cadence_gate(events, GAPS)

    def test_cross_lineage_generations_are_independent(self):
        events = [
            UpdateOpportunity("MEM", 1, 15, True, True),
            UpdateOpportunity("ACT", 1, 2, True, True),
            UpdateOpportunity("MEM", 2, 15, True, False),
            UpdateOpportunity("ACT", 17, 3, True, True),
        ]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["REVIEW_CANDIDATE", "REVIEW_CANDIDATE",
                          "NO_UPDATE", "REVIEW_CANDIDATE"])
        self.assertTrue(all(r["authority"] == "DENY_ALL" for r in rows))

    def test_equal_generation_retry_is_not_auto_promoted(self):
        events = [
            UpdateOpportunity("PERC", 1, 5, True, True),
            UpdateOpportunity("PERC", 2, 5, True, True),
            UpdateOpportunity("PERC", 17, 5, False, True),
        ]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["REVIEW_CANDIDATE", "NO_UPDATE", "NO_UPDATE"])


if __name__ == "__main__":
    unittest.main()
