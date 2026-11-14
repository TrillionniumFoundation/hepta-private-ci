"""Tests for the exact zero-numerical operator/segment roster review."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_operator_segment_roster import review


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001"
ROSTER = (
    ROOT
    / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001"
)
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_operator_segment_roster"


def run_review(metadata=None, roster=None):
    return review.review_operator_segment_rosters(
        metadata or INPUT / "METADATA.json",
        INPUT / "N256_STATE.json",
        INPUT / "N256_PHASE.json",
        INPUT / "N256_STATE.npz.b64",
        roster or ROSTER,
    )


class OperatorSegmentRosterReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certificate = run_review()

    def test_exact_certificate(self):
        certificate = self.certificate
        self.assertEqual(certificate.unique_operators, 4)
        self.assertEqual(certificate.operator_nnz, 3058)
        self.assertEqual(certificate.unique_sparse_operator_bytes, 44912)
        self.assertEqual(certificate.transition_segments, 45)
        self.assertEqual(certificate.emitted_templates, 71)
        self.assertEqual(certificate.initial_templates, 8)
        self.assertEqual(certificate.operator_roster_sha256, review.EXPECTED_OPERATOR_ROSTER_SHA256)
        self.assertEqual(certificate.segment_roster_sha256, review.EXPECTED_SEGMENT_ROSTER_SHA256)
        self.assertFalse(certificate.numerical_execution_allowed)
        self.assertFalse(certificate.provider_admitted)
        self.assertFalse(certificate.largegrid_qualification)
        self.assertFalse(certificate.all_closed)
        self.assertEqual(
            certificate.dynamic_calls
            + certificate.matrix_exponential_calls
            + certificate.oracle_calls
            + certificate.serializer_calls
            + certificate.torch_calls
            + certificate.optimizer_calls
            + certificate.model_calls
            + certificate.provider_calls,
            0,
        )

    def test_published_canonical_rosters(self):
        operators = json.loads((PACKAGE / "OPERATOR_ROSTER.json").read_text())
        segments = [
            json.loads(line)
            for line in (PACKAGE / "SEGMENT_ROSTER.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(operators), 4)
        self.assertEqual(len(segments), 45)
        self.assertEqual(sum(item["nnz"] for item in operators), 3058)
        self.assertEqual(sum(item["csr_bytes"] for item in operators), 44912)
        self.assertEqual(sum(len(item["emitted"]) for item in segments), 71)
        self.assertEqual(
            review._digest(review._canonical(operators)),
            review.EXPECTED_OPERATOR_ROSTER_SHA256,
        )
        self.assertEqual(
            review._digest(review._canonical(segments)),
            review.EXPECTED_SEGMENT_ROSTER_SHA256,
        )

    def test_event_original_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "roster"
            shutil.copytree(ROSTER, copied)
            events = copied / "EVENTS.jsonl"
            events.write_bytes(events.read_bytes() + b"\n")
            with self.assertRaisesRegex(review.RosterReviewError, "roster-original"):
                run_review(roster=copied)

    def test_input_original_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            metadata = Path(temporary) / "METADATA.json"
            metadata.write_bytes((INPUT / "METADATA.json").read_bytes() + b"\n")
            with self.assertRaisesRegex(review.RosterReviewError, "input-original"):
                run_review(metadata=metadata)


if __name__ == "__main__":
    unittest.main()
