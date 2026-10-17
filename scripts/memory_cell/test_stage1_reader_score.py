"""Parity of lightweight read-only task scoring with frozen native QA rules."""

import unittest

from stage1_reader_score import ABSTAIN, answer_scores, normalized


class ReadOnlyTaskScoreTests(unittest.TestCase):
    def test_citations_removed_only_for_diagnostic_scoring(self):
        self.assertEqual(normalized("The Fact! [E3]"), "fact")
        self.assertEqual(
            answer_scores("The Fact! [E3]", ("a fact",), False),
            dict(exact_match=1.0, f1=1.0),
        )

    def test_legacy_token_overlap_and_empty_answer(self):
        result = answer_scores("two details", ("two unrelated details",), False)
        self.assertEqual(result["exact_match"], 0)
        self.assertAlmostEqual(result["f1"], 0.8)
        self.assertEqual(
            answer_scores("", ("result",), False),
            dict(exact_match=0.0, f1=0.0),
        )

    def test_unanswerable_needs_actual_abstention(self):
        self.assertEqual(
            answer_scores(ABSTAIN, ("unused",), True),
            dict(exact_match=1.0, f1=1.0),
        )
        self.assertEqual(
            answer_scores("plausible", ("unused",), True),
            dict(exact_match=0.0, f1=0.0),
        )

    def test_missing_gold_stays_unscored(self):
        self.assertEqual(
            answer_scores("response", None, None),
            dict(exact_match=None, f1=None),
        )
        with self.assertRaisesRegex(ValueError, "missing gold answer"):
            answer_scores("response", (), False)


if __name__ == "__main__":
    unittest.main()
