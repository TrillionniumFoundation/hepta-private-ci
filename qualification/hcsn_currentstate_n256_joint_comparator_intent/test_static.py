"""Small stdlib fixtures only; no N256 implementation is imported or invoked."""

import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_joint_comparator_intent import contract
from qualification.hcsn_currentstate_n256_joint_comparator_intent.full_coordinate_comparator import (
    compare_coordinate_streams,
)
from qualification.hcsn_currentstate_n256_joint_comparator_intent.joint_runner_contract import (
    validate_future_manifest,
)


ROOT = Path(__file__).parent


def row(sequence, lane, lane_order, value):
    return {
        "sequence": sequence,
        "capsule_order": sequence,
        "lane": lane,
        "lane_order": lane_order,
        "time_numerator": sequence,
        "time_denominator": 1,
        "surface": "active",
        "packet_identity": f"packet-{sequence}",
        "generation": 1,
        "origin": 0,
        "target": 1,
        "support_start_numerator": 0,
        "support_start_denominator": 1,
        "support_end_numerator": 1,
        "support_end_denominator": 1,
        "coordinate_index": 0,
        "value_hex": value,
    }


class ComparatorSourceIntentTest(unittest.TestCase):
    def test_request_is_exact_source_only_hold(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(contract.validate_source_request(request), request)
        with self.assertRaises(contract.AdmissionRequired):
            contract.require_execution_admission(ROOT / "REQUEST.json", None)

    def test_small_fixture_keeps_candidate_and_oracle_errors_separate(self):
        reference = [
            row(0, "warm", 0, "0x1.0000000000000p+0"),
            row(1, "coarse", 0, "0x1.0000000000000p+1"),
            row(2, "cold", 0, "0x1.8000000000000p+1"),
        ]
        candidate = copy.deepcopy(reference)
        oracle = copy.deepcopy(reference)
        candidate[0]["value_hex"] = "0x1.0000000000001p+0"
        oracle[1]["value_hex"] = "0x1.0000000000001p+1"
        report = compare_coordinate_streams(candidate, oracle, reference, 3)
        self.assertEqual(report["records"], 3)
        self.assertEqual(report["candidate_max_abs_error_hex"], "0x1.0000000000000p-52")
        self.assertEqual(report["oracle_max_abs_error_hex"], "0x1.0000000000000p-51")
        self.assertFalse(report["signed_error_cancellation_used"])

    def test_reordered_or_identity_mismatched_stream_rejects(self):
        reference = [row(0, "warm", 0, "0x1.0000000000000p+0")]
        candidate = copy.deepcopy(reference)
        oracle = copy.deepcopy(reference)
        oracle[0]["coordinate_index"] = 1
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            compare_coordinate_streams(candidate, oracle, reference, 1)
        oracle = copy.deepcopy(reference)
        candidate[0]["sequence"] = 1
        oracle[0]["sequence"] = 1
        reference[0]["sequence"] = 1
        with self.assertRaisesRegex(ValueError, "contiguous canonical order"):
            compare_coordinate_streams(candidate, oracle, reference, 1)

    def test_denominator_and_noncanonical_values_reject(self):
        reference = [row(0, "warm", 0, "0x0.0p+0")]
        with self.assertRaisesRegex(ValueError, "denominator mismatch"):
            compare_coordinate_streams(reference, reference, reference, 2)
        bad = copy.deepcopy(reference)
        bad[0]["value_hex"] = "-0x0.0p+0"
        with self.assertRaisesRegex(ValueError, "non-negative-zero"):
            compare_coordinate_streams(bad, reference, reference, 1)

    def test_future_manifest_requires_three_exact_pairs_and_separate_gates(self):
        digest = "a" * 64
        manifest = {
            "coordinate_denominator": contract.EXPECTED_DENOMINATOR,
            "capsules": contract.EXPECTED_CAPSULES,
            "lane_capsules": contract.EXPECTED_LANE_CAPSULES,
            "frame_order_contiguous": True,
            "coordinate_identity_equal": True,
            "signed_error_cancellation_used": False,
            "separate_error_gates": {
                name: {
                    "passed": True,
                    "max_abs_error_hex": "0x0.0p+0",
                    "sum_abs_error_hex": "0x0.0p+0",
                    "threshold_hex": "0x1.0p-10",
                }
                for name in ("candidate", "oracle")
            },
            "byte_exact_pairs": [
                {
                    "name": name,
                    "producer_sha256": digest,
                    "cold_loader_sha256": digest,
                    "producer_bytes": 8,
                    "cold_loader_bytes": 8,
                }
                for name in contract.BYTE_PAIR_NAMES
            ],
            "execution_key_reused_from_frozen_lane_contracts": True,
        }
        self.assertEqual(validate_future_manifest(manifest), manifest)
        cancelled = copy.deepcopy(manifest)
        cancelled["signed_error_cancellation_used"] = True
        with self.assertRaisesRegex(ValueError, "cancellation"):
            validate_future_manifest(cancelled)
        not_exact = copy.deepcopy(manifest)
        not_exact["byte_exact_pairs"][2]["cold_loader_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "not byte exact"):
            validate_future_manifest(not_exact)


if __name__ == "__main__":
    unittest.main()
