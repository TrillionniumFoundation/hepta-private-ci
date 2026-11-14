"""Clock-frontier monotonicity tests; shadow-only, no owner authority."""
import unittest
from study import ContractError, UpdateOpportunity, cadence_gate

GAPS = {"PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
        "VERIFY": 8, "ACT": 16, "LEARN": 16}

class SequenceFrontierTests(unittest.TestCase):
    def test_clock_denied_event_still_advances_observed_sequence(self):
        events = [UpdateOpportunity("PERC", 1, 1, True, True),
                  UpdateOpportunity("PERC", 10, 2, True, True),
                  UpdateOpportunity("PERC", 9, 3, True, True)]
        with self.assertRaisesRegex(ContractError, "clock regression"):
            cadence_gate(events, GAPS)

    def test_evidence_denied_event_still_advances_observed_sequence(self):
        events = [UpdateOpportunity("CTRL", 1, 1, True, True),
                  UpdateOpportunity("CTRL", 100, 2, False, False),
                  UpdateOpportunity("CTRL", 20, 3, True, True)]
        with self.assertRaisesRegex(ContractError, "clock regression"):
            cadence_gate(events, GAPS)

    def test_lineage_interleaving_and_equal_sequence_remain_valid(self):
        events = [UpdateOpportunity("PERC", 10, 2, False, False),
                  UpdateOpportunity("MEM", 1, 7, True, True),
                  UpdateOpportunity("PERC", 10, 2, True, True),
                  UpdateOpportunity("MEM", 2, 7, True, False),
                  UpdateOpportunity("PERC", 26, 3, True, True)]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["NO_UPDATE", "REVIEW_CANDIDATE", "NO_UPDATE",
                          "NO_UPDATE", "REVIEW_CANDIDATE"])
        self.assertTrue(all(r["authority"] == "DENY_ALL" for r in rows))

if __name__ == "__main__":
    unittest.main()
