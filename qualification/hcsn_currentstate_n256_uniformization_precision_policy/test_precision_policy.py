import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_uniformization_precision_policy.precision_policy import (
    CERTIFICATE_SCHEMA,
    ORIGINAL_SCALED_ERROR_LIMIT,
    POLICY_SCHEMA,
    PrecisionPolicyError,
    outward_nonnegative_sum,
    validate_precision_certificate,
)


def fixture():
    record = {
        "schema": CERTIFICATE_SCHEMA,
        "policy_sha256": "1" * 64,
        "provider_source_sha256": "2" * 64,
        "provider_admission_sha256": "3" * 64,
        "operator_identity": "4" * 64,
        "roster_identity": "5" * 64,
        "lane": "warm",
        "left_fraction": [0, 1],
        "right_fraction": [1, 1000],
        "input_l1_fp64_hex": 2.0.hex(),
        "truncation_index": 9,
        "recurrence_terms": 10,
        "poisson_tail_upper_fp64_hex": 0.001.hex(),
        "sparse_row_action_rounding_upper_fp64_hex": 0.001.hex(),
        "poisson_recurrence_rounding_upper_fp64_hex": 0.001.hex(),
        "accumulation_rounding_upper_fp64_hex": 0.001.hex(),
        "serialization_rounding_upper_fp64_hex": 0.001.hex(),
        "total_provider_error_upper_fp64_hex": 0.006.hex(),
        "original_scaled_error_limit_fp64_hex": ORIGINAL_SCALED_ERROR_LIMIT.hex(),
        "scientific_certifications": {
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
    return record


class PrecisionPolicyTests(unittest.TestCase):
    def test_policy_identity_and_outward_composition(self):
        self.assertEqual(POLICY_SCHEMA, "hcsn-n256-uniformization-precision-policy-v1")
        result = validate_precision_certificate(fixture(), "2" * 64, "3" * 64)
        self.assertEqual(result.component_count, 5)
        self.assertTrue(result.within_original_limit)
        self.assertFalse(result.provider_admitted)
        self.assertEqual(result.n256_provider_calls, 0)
        self.assertEqual(result.tail_certificates_admitted, 0)

    def test_outward_sum_does_not_round_inward(self):
        values = (0.001, 0.001, 0.001, 0.001, 0.001)
        self.assertGreater(outward_nonnegative_sum(values), sum(values))

    def test_changed_original_limit_is_rejected(self):
        record = fixture()
        record["original_scaled_error_limit_fp64_hex"] = 0.02.hex()
        with self.assertRaisesRegex(PrecisionPolicyError, "original scaled"):
            validate_precision_certificate(record, "2" * 64, "3" * 64)

    def test_understated_total_is_rejected(self):
        record = fixture()
        record["total_provider_error_upper_fp64_hex"] = 0.004.hex()
        with self.assertRaisesRegex(PrecisionPolicyError, "understates"):
            validate_precision_certificate(record, "2" * 64, "3" * 64)

    def test_missing_scientific_claim_is_rejected(self):
        record = fixture()
        del record["scientific_certifications"]["fp64_rounding"]
        with self.assertRaisesRegex(PrecisionPolicyError, "incomplete"):
            validate_precision_certificate(record, "2" * 64, "3" * 64)


if __name__ == "__main__":
    unittest.main()

