import json
from pathlib import Path
import tempfile
import unittest

from reader_four_arm_diagnostic import (
    ARMS,
    DeterministicReader,
    JsonlReaderBackend,
    ReaderEvidence,
    ValidationError,
    default_cases,
    run_diagnostic,
    token_f1,
    _reader_request_digest,
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
            def answer(self, question, evidence):
                if evidence and evidence[0].kind == "ordinary":
                    raise RuntimeError("controlled failure")
                return super().answer(question, evidence)

        report = run_diagnostic(default_cases()[:2], backend=FailingReader())
        ordinary = report["arms_report"]["ordinary_retrieval"]
        self.assertEqual(ordinary["failed"], 2)
        self.assertEqual(report["reader_identity"], "failing-fixture")

    def test_backend_receives_no_gold_or_evaluator_labels(self):
        class InspectingReader(DeterministicReader):
            identity = "inspecting-fixture"

            def __init__(self):
                self.calls = []

            def answer(self, question, evidence):
                self.calls.append((question, evidence))
                self.assert_input(evidence)
                return super().answer(question, evidence)

            @staticmethod
            def assert_input(evidence):
                for item in evidence:
                    if not isinstance(item, ReaderEvidence):
                        raise AssertionError("backend received evaluator Evidence")
                    if hasattr(item, "is_key_premise"):
                        raise AssertionError("backend received key-premise label")

        backend = InspectingReader()
        report = run_diagnostic(default_cases()[:1], backend=backend)
        self.assertEqual(len(backend.calls), len(ARMS))
        self.assertEqual(report["arms_report"]["sufficient_evidence"]["exact_count"], 1)

    def test_external_answers_are_replayed_by_public_input_digest(self):
        case = default_cases()[0]
        rows_by_digest = {}
        for arm in ARMS:
            evidence = {
                "no_evidence": (),
                "ordinary_retrieval": case.ordinary_evidence,
                "sufficient_evidence": case.sufficient_evidence,
                "key_premise_removed": (),
            }[arm]
            public = tuple(ReaderEvidence(x.evidence_id, x.text, x.kind) for x in evidence)
            digest = _reader_request_digest(case.question, public)
            rows_by_digest[digest] = {"request_digest": digest, "answer": case.gold_answer}
        backend = JsonlReaderBackend(tuple(rows_by_digest.values()))
        report = run_diagnostic((case,), backend=backend)
        self.assertEqual(report["benchmark_mode"], "external_observation")
        self.assertEqual(report["arms_report"]["sufficient_evidence"]["exact_count"], 1)

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
