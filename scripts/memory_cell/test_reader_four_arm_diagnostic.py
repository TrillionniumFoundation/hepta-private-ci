import json
from pathlib import Path
import tempfile
import unittest

from reader_four_arm_diagnostic import (
    ARMS,
    DeterministicReader,
    ValidationError,
    default_cases,
    run_diagnostic,
    token_f1,
)


class ReaderFourArmDiagnosticTests(unittest.TestCase):
    def test_four_arms_are_matched_and_sufficient_evidence_is_scored_after_raw_seal(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            report = run_diagnostic(default_cases(), output_dir=output)
            self.assertEqual(report["schema"], "hepta.experiment2-reader-four-arm.v1")
            self.assertEqual(report["planned_attempts"], 32)
            self.assertEqual(tuple(report["arms"]), ARMS)
            self.assertFalse(report["production_accepted"])
            self.assertTrue((output / "raw-answers.jsonl").is_file())
            self.assertTrue((output / "report.json").is_file())
            rows = [json.loads(line) for line in (output / "raw-answers.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 32)
            self.assertEqual({row["arm"] for row in rows}, set(ARMS))
            self.assertGreater(report["arms_report"]["sufficient_evidence"]["mean_diagnostic_f1"], 0.99)
            diagnoses = {x["diagnosis"] for x in report["per_question"]}
            self.assertIn("retrieval_or_head", diagnoses)

    def test_backend_identity_and_failures_are_recorded_per_arm(self):
        class FailingReader(DeterministicReader):
            identity = "failing-fixture"
            def answer(self, question, evidence, *, arm):
                if arm == "ordinary_retrieval":
                    raise RuntimeError("controlled failure")
                return super().answer(question, evidence, arm=arm)

        report = run_diagnostic(default_cases()[:2], backend=FailingReader())
        ordinary = report["arms_report"]["ordinary_retrieval"]
        self.assertEqual(ordinary["failed"], 2)
        self.assertEqual(report["reader_identity"], "failing-fixture")

    def test_invalid_case_without_key_premise_is_rejected(self):
        case = default_cases()[0]
        bad = case.__class__(case.question_id, case.question, case.gold_answer, case.ordinary_evidence, tuple(), case.family)
        with self.assertRaises(ValidationError):
            run_diagnostic((bad,))

    def test_token_f1_is_only_a_literal_diagnostic(self):
        self.assertEqual(token_f1("Kyoto", "Kyoto"), 1.0)
        self.assertEqual(token_f1("wrong", "Kyoto"), 0.0)


if __name__ == "__main__":
    unittest.main()
