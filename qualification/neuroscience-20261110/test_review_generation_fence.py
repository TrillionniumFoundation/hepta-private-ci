"""One review opportunity per lineage and candidate generation (shadow-only)."""
import unittest
from study import UpdateOpportunity, cadence_gate

GAPS = {
    "PERC": 16, "MEM": 1, "PRED": 8, "CTRL": 4,
    "VERIFY": 8, "ACT": 16, "LEARN": 16,
}

def e(lineage, sequence, generation, independent=True, passed=True):
    return UpdateOpportunity(lineage, sequence, generation, independent, passed)

class DuplicateReviewedGenerationTests(unittest.TestCase):
    def test_same_generation_cannot_be_reviewed_twice_after_clock_gap(self):
        events = [e("PERC", 1, 5), e("PERC", 17, 5), e("PERC", 33, 6)]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["REVIEW_CANDIDATE", "NO_UPDATE", "REVIEW_CANDIDATE"])
        self.assertEqual(rows[1]["reason"], "duplicate_reviewed_generation")
        self.assertTrue(all(r["authority"] == "DENY_ALL" for r in rows))

    def test_evidence_denied_can_receive_first_review_when_new_evidence_arrives(self):
        events = [e("CTRL", 1, 8, False, False),
                  e("CTRL", 5, 8, True, True),
                  e("CTRL", 9, 8, True, True),
                  e("CTRL", 13, 9, True, True)]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["NO_UPDATE", "REVIEW_CANDIDATE", "NO_UPDATE",
                          "REVIEW_CANDIDATE"])

    def test_duplicate_attempt_consumes_its_allowed_clock_slot(self):
        events = [e("PERC", 1, 2), e("PERC", 17, 2),
                  e("PERC", 18, 3), e("PERC", 33, 3)]
        rows = cadence_gate(events, GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["REVIEW_CANDIDATE", "NO_UPDATE", "NO_UPDATE",
                          "REVIEW_CANDIDATE"])
        self.assertEqual(rows[2]["reason"], "clock_gate")

    def test_same_generation_across_separate_lineages_remains_independent(self):
        rows = cadence_gate([e("PERC", 1, 7), e("ACT", 1, 7)], GAPS)
        self.assertEqual([r["status"] for r in rows],
                         ["REVIEW_CANDIDATE", "REVIEW_CANDIDATE"])

if __name__ == "__main__":
    unittest.main()
