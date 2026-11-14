import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_provider_intent.provider import (
    ProviderCounts,
    ProviderError,
    SparseSubgenerator,
    require_execution_admission,
    stable_poisson_window,
    synthetic_uniformization_action,
    validate_external_certificate,
)


class ProviderSourceTests(unittest.TestCase):
    def setUp(self):
        self.operator = SparseSubgenerator.from_rows(
            (
                ((0, -2.0), (1, 2.0)),
                ((1, 0.0),),
            )
        )

    def test_small_synthetic_action_and_counts(self):
        counts = ProviderCounts()
        result = synthetic_uniformization_action(
            self.operator, (1.0, -0.25), 0.5, 2.0, 24, counts
        )
        expected = -0.25 + 1.0 - math.exp(-1.0)
        self.assertAlmostEqual(result.values[0], math.exp(-1.0), places=14)
        self.assertAlmostEqual(result.values[1], expected, places=14)
        self.assertEqual(counts.synthetic_provider_calls, 1)
        self.assertEqual(counts.sparse_row_actions, 24)
        self.assertEqual(counts.poisson_recurrence_terms, 25)
        self.assertEqual(counts.n256_provider_calls, 0)
        self.assertFalse(result.fp64_rounding_certified)
        self.assertFalse(result.provider_admitted)
        self.assertFalse(result.largegrid_qualification)

    def test_large_intensity_window_avoids_underflow_start(self):
        window = stable_poisson_window(13461.075, 13460)
        self.assertEqual(len(window.weights), 13461)
        self.assertGreater(window.weights[-1], 0.0)
        self.assertTrue(math.isfinite(window.tail_upper))
        self.assertGreater(window.tail_upper, 0.0)
        mode = math.floor(window.intensity)
        modal = math.exp(
            -window.intensity
            + mode * math.log(window.intensity)
            - math.lgamma(mode + 1.0)
        )
        expected_upper = modal / (1.0 - window.intensity / (mode + 1.0))
        self.assertEqual(window.tail_upper, expected_upper)

    def test_operator_and_rate_guards(self):
        with self.assertRaisesRegex(ProviderError, "off-diagonal"):
            SparseSubgenerator.from_rows((((0, -1.0), (1, -1.0)), ((1, 0.0),)))
        with self.assertRaisesRegex(ProviderError, "below an exit"):
            self.operator.transition_rows(1.0)
        with self.assertRaisesRegex(ProviderError, "decreasing ratio"):
            stable_poisson_window(8.5, 6)

    def test_external_certificate_is_identity_bound(self):
        result = synthetic_uniformization_action(self.operator, (1.0, 0.0), 0.2, 2.0, 12)
        record = {
            "schema": "certified_sparse_uniformization_v1",
            "provider_source_sha256": "a" * 64,
            "provider_admission_sha256": "b" * 64,
            "operator_identity": result.operator_identity,
            "poisson_intensity_fp64_hex": result.intensity_hex,
            "truncation_index": result.truncation_index,
            "input_l1_fp64_hex": result.input_l1_hex,
            "poisson_tail_upper_fp64_hex": result.poisson_tail_upper_hex,
            "rounding_upper_fp64_hex": 0.0.hex(),
            "signed_l1_output_upper_fp64_hex": 1.0.hex(),
            "recurrence_terms": result.recurrence_terms,
            "certifications": {
                "permanent_nonreturning_upper_escape": True,
                "deterministic_delay_and_reset": True,
                "signed_l1_tail": True,
                "discounted_hit_and_occupation": True,
                "fp64_rounding": True,
                "every_emitted_roster_operator": True,
            },
        }
        record["certificate_sha256"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertTrue(validate_external_certificate(record, result, "a" * 64, "b" * 64))
        changed = dict(record)
        changed["operator_identity"] = "c" * 64
        with self.assertRaisesRegex(ProviderError, "identity mismatch"):
            validate_external_certificate(changed, result, "a" * 64, "b" * 64)

    def test_current_request_cannot_admit_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory, "REQUEST.json")
            admission = Path(directory, "ADMISSION.json")
            request.write_text(json.dumps({"numerical_execution_allowed": False}))
            admission.write_text(json.dumps({"admitted": True}))
            with self.assertRaisesRegex(ProviderError, "not allowed"):
                require_execution_admission(request, admission, "a" * 64)


if __name__ == "__main__":
    unittest.main()

