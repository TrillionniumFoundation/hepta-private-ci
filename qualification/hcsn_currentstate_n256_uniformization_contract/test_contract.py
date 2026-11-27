import ast
import json
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_contract.stiffness_review import (
    StiffnessReviewError,
    TAIL_CERTIFICATE_ENVELOPE,
    review_event_records,
    review_frozen_stiffness,
    validate_tail_certificate_envelope,
)


ROOT = Path(__file__).resolve().parents[2]
ORIGINALS = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001"
GENERATOR = ROOT / "qualification/hcsn_currentstate_n256_exact_generator_review"
EVENTS = ROOT / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/EVENTS.jsonl"


class N256UniformizationContractTest(unittest.TestCase):
    @unittest.skipUnless(EVENTS.exists(), "exact Git roster original is not materialized locally")
    def test_exact_stiffness_envelope(self):
        certificate = review_frozen_stiffness(
            GENERATOR / "generator_review.py",
            GENERATOR / "REQUEST.json",
            EVENTS,
            ORIGINALS / "METADATA.json",
            ORIGINALS / "N256_STATE.json",
            ORIGINALS / "N256_PHASE.json",
            ORIGINALS / "N256_STATE.npz.b64",
        )
        self.assertEqual(certificate.generator_rows, 255)
        self.assertEqual(certificate.transition_segments, 45)
        self.assertEqual(
            (certificate.warm_segments, certificate.coarse_segments, certificate.cold_segments),
            (21, 15, 9),
        )
        self.assertEqual(certificate.uniformization_rate_integer, 538443)
        self.assertEqual(certificate.maximum_segment_duration_fraction, "1/40")
        self.assertEqual(certificate.maximum_poisson_intensity_fraction, "538443/40")
        self.assertEqual(certificate.ratio_tail_precondition_minimum_truncation_index, 13460)
        self.assertEqual(certificate.ratio_tail_precondition_minimum_recurrence_terms, 13461)
        self.assertEqual(certificate.tail_certificates_admitted, 0)
        self.assertFalse(certificate.provider_admitted)
        self.assertFalse(certificate.largegrid_qualification)
        self.assertEqual(certificate.dynamic_calls, 0)
        self.assertEqual(certificate.matrix_exponential_calls, 0)
        self.assertEqual(certificate.poisson_recurrence_calls, 0)

    def test_event_review_rejects_a_gap(self):
        records = []
        for lane, count, start in (("warm", 21, 0), ("coarse", 15, 0), ("cold", 9, 201)):
            denominator = 1000
            end = 360
            widths = [1] * (count - 1) + [end - start - count + 1]
            left = start
            for width in widths:
                right = left + width
                records.append(
                    {
                        "kind": "transition",
                        "lane": lane,
                        "left": {"fraction": [left, denominator]},
                        "right": {"fraction": [right, denominator]},
                        "releasing": 1,
                    }
                )
                left = right
        records.append(
            {"kind": "cold_restore", "lane": "cold", "time": {"fraction": [201, 1000]}}
        )
        durations, counts = review_event_records(records)
        self.assertEqual(len(durations), 45)
        self.assertEqual(counts, {"warm": 21, "coarse": 15, "cold": 9})
        records[1]["left"]["fraction"] = [0, 1000]
        with self.assertRaisesRegex(StiffnessReviewError, "not contiguous"):
            review_event_records(records)

    def test_tail_envelope_is_fail_closed(self):
        record = {
            "schema": TAIL_CERTIFICATE_ENVELOPE["schema"],
            **{name: "bound" for name in TAIL_CERTIFICATE_ENVELOPE["required"]},
            "truncation_index": 13460,
            "recurrence_terms": 13461,
            "certifications": {
                name: True for name in TAIL_CERTIFICATE_ENVELOPE["required_certifications"]
            },
        }
        self.assertTrue(validate_tail_certificate_envelope(record))
        record["provider_admission_sha256"] = None
        with self.assertRaisesRegex(StiffnessReviewError, "identity is null"):
            validate_tail_certificate_envelope(record)

    def test_source_excludes_numeric_execution(self):
        source = (Path(__file__).parent / "stiffness_review.py").read_text()
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertFalse(imported & {"numpy", "scipy", "torch"})
        self.assertNotIn("expm_multiply", source)
        self.assertNotIn("sparse_dynamic_intent", source)
        self.assertNotIn("independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()
