"""Whole-arm confounds must not masquerade as parameter-memory improvement."""

import unittest

from factorial_evidence_gate import analyze
from test_factorial_evidence_gate import fixture, digest


class MatchedContrastTests(unittest.TestCase):
    def test_whole_arm_reader_and_prompt_replacement(self):
        for field in ("reader_revision", "prompt_digest"):
            plan, rows = fixture()
            for row in rows:
                if row["arm"] == "knowledge":
                    row[field] = digest("replacement")
                    row["success"] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                analyze(plan, rows)

    def test_equal_evidence_is_required_for_each_parameter_candidate(self):
        for arm in ("learned_read", "knowledge"):
            plan, rows = fixture()
            for row in rows:
                if row["arm"] == arm:
                    row["source_digest"] = digest("extra-answer-evidence")
                    row["success"] = True
            with self.subTest(arm=arm), self.assertRaises(ValueError):
                analyze(plan, rows)

    def test_reference_cannot_receive_different_evidence(self):
        plan, rows = fixture()
        for row in rows:
            if row["reader"] == "reference":
                row["source_digest"] = digest("larger-reference-context")
        with self.assertRaises(ValueError):
            analyze(plan, rows)

    def test_reader_revision_cannot_change_by_question(self):
        plan, rows = fixture()
        for row in rows:
            if row["id"] == "case-0":
                row["reader_revision"] = "replacement"
        with self.assertRaises(ValueError):
            analyze(plan, rows)

    def test_unknown_lifetime_terms_are_not_zero(self):
        plan, rows = fixture()
        for row in rows:
            row["cost"]["maintenance"] = None
        report = analyze(plan, rows)
        measured = report["arms"]["hybrid_rag"]["frozen"]["hybrid"]
        self.assertIsNone(measured["total_cost"]["maintenance"])
        self.assertEqual(measured["missing_cost_measurements"]["maintenance"], 4)
        self.assertFalse(report["production_qualified"])

    def test_candidates_are_rejected_individually(self):
        plan, rows = fixture()
        for row in rows:
            if row["arm"] == "knowledge" and row["condition"] == "hybrid":
                row["success"] = True
        report = analyze(plan, rows)
        self.assertTrue(report["diagnosis"]["candidate_rejected"]["learned_read"])
        self.assertFalse(report["diagnosis"]["candidate_rejected"]["knowledge"])
        self.assertFalse(report["parametric_learning_qualified"])


if __name__ == "__main__":
    unittest.main()
