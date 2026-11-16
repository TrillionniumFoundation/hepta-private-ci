"""Small stdlib fixtures; no N256 numerical implementation is invoked."""

import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_reference_stream_intent import (
    reference_stream_contract as contract,
)


ROOT = Path(__file__).parent


def row(sequence, capsule, lane, lane_order, value="0x0.0p+0"):
    return {
        "sequence": sequence,
        "capsule_order": capsule,
        "lane": lane,
        "lane_order": lane_order,
        "time_numerator": sequence,
        "time_denominator": 1,
        "surface": "active",
        "packet_identity": f"fixture-packet-{sequence}",
        "generation": 1,
        "origin": 0,
        "target": 1,
        "support_start_numerator": 0,
        "support_start_denominator": 1,
        "support_end_numerator": 1,
        "support_end_denominator": 1,
        "coordinate_index": sequence,
        "value_hex": value,
    }


class ReferenceStreamInterfaceTest(unittest.TestCase):
    def test_request_is_exact_source_only_hold(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(contract.validate_request(request), request)
        with self.assertRaises(contract.AdmissionRequired):
            contract.require_reference_execution_admission(ROOT / "REQUEST.json", None)

    def test_small_canonical_stream_has_stable_digest(self):
        rows = [
            row(0, 0, "warm", 0, "0x1.0000000000000p+0"),
            row(1, 8, "coarse", 0, "-0x1.0000000000000p-1"),
            row(2, 11, "cold", 0, "0x0.0p+0"),
        ]
        first = contract.validate_reference_rows(rows, 3)
        second = contract.validate_reference_rows(copy.deepcopy(rows), 3)
        self.assertEqual(first, second)
        self.assertEqual(first["records"], 3)
        self.assertFalse(first["numerical_execution_performed_by_validator"])

    def test_identity_order_and_canonical_values_fail_closed(self):
        base = [row(0, 0, "warm", 0)]
        bad = copy.deepcopy(base)
        bad[0]["sequence"] = 1
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            contract.validate_reference_rows(bad, 1)
        bad = copy.deepcopy(base)
        bad[0]["capsule_order"] = 8
        with self.assertRaisesRegex(ValueError, "capsule and lane"):
            contract.validate_reference_rows(bad, 1)
        bad = copy.deepcopy(base)
        bad[0]["value_hex"] = "-0x0.0p+0"
        with self.assertRaisesRegex(ValueError, "negative zero"):
            contract.validate_reference_rows(bad, 1)
        bad = copy.deepcopy(base)
        bad[0]["extra"] = True
        with self.assertRaisesRegex(ValueError, "field set"):
            contract.validate_reference_rows(bad, 1)

    def test_denominator_and_fraction_guards_do_not_use_assert(self):
        base = [row(0, 0, "warm", 0)]
        with self.assertRaisesRegex(ValueError, "denominator mismatch"):
            contract.validate_reference_rows(base, 2)
        bad = copy.deepcopy(base)
        bad[0]["time_numerator"] = 2
        bad[0]["time_denominator"] = 2
        with self.assertRaisesRegex(ValueError, "reduced fraction"):
            contract.validate_reference_rows(bad, 1)

    def test_provenance_requires_distinct_precommitted_provider(self):
        digest = "a" * 64
        provenance = {
            "schema": contract.SCHEMA,
            "input_bundle_sha256": contract.INPUT_BUNDLE_SHA256,
            "roster_identity": contract.ROSTER_IDENTITY,
            "candidate_source_sha256": contract.CANDIDATE_SOURCE_SHA256,
            "oracle_source_sha256": contract.ORACLE_SOURCE_SHA256,
            "comparator_source_sha256": contract.COMPARATOR_SOURCE_SHA256,
            "reference_provider_source_sha256": digest,
            "reference_provider_admission_sha256": "b" * 64,
            "independence_review_sha256": "c" * 64,
            "runtime_profile_sha256": "d" * 64,
            "method_id": "independent_reference_v1",
            "precommitted_source": True,
            "imports_candidate_or_oracle": False,
            "shared_numeric_kernel": False,
        }
        self.assertEqual(contract.validate_provenance(provenance), provenance)
        reused = copy.deepcopy(provenance)
        reused["reference_provider_source_sha256"] = contract.ORACLE_SOURCE_SHA256
        with self.assertRaisesRegex(ValueError, "not independent"):
            contract.validate_provenance(reused)
        shared = copy.deepcopy(provenance)
        shared["shared_numeric_kernel"] = True
        with self.assertRaisesRegex(ValueError, "shared_numeric_kernel mismatch"):
            contract.validate_provenance(shared)


if __name__ == "__main__":
    unittest.main()
