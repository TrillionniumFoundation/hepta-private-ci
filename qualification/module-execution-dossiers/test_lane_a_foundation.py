"""Closed-world tests for Lane A current implementation truth."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_lane_a_foundation.py"
SPEC = importlib.util.spec_from_file_location("verify_lane_a_foundation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class LaneAFoundationTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = verify.read_json(verify.MATRIX_PATH)
        cls.capability_map = verify.read_json(verify.CAPABILITY_MAP_PATH)

    def test_exact_repository_truth_is_valid(self) -> None:
        verify.validate_matrix(self.matrix)

    def test_closed_world_module_set(self) -> None:
        self.assertEqual(
            [row["module"] for row in self.matrix["modules"]],
            verify.EXPECTED_MODULES,
        )
        self.assertEqual(self.matrix["moduleCoverage"], 7)

    def test_every_current_capability_has_one_evidence_mapping(self) -> None:
        verify.validate_capability_map(self.matrix, self.capability_map)
        expected = sum(
            len(row["currentCapabilities"]) for row in self.matrix["modules"]
        )
        self.assertEqual(self.capability_map["entryCount"], expected)
        self.assertEqual(expected, 21)

    def test_operations_cannot_claim_unimplemented_durability(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][3]["states"]["durability"] = "durable"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_authbus_cannot_claim_authentication_policy_or_quota(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][5]["currentCapabilities"].append(
            "cryptographic signature verification"
        )
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_repository_cannot_self_grant_acceptance(self) -> None:
        value = deepcopy(self.matrix)
        value["closure"]["externalAcceptance"] = "closed"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_current_and_target_capabilities_are_disjoint(self) -> None:
        for row in self.matrix["modules"]:
            self.assertFalse(
                set(row["currentCapabilities"]) & set(row["targetOnlyCapabilities"])
            )

    def test_missing_capability_mapping_is_rejected(self) -> None:
        value = deepcopy(self.capability_map)
        value["entries"].pop()
        with self.assertRaises(verify.VerificationError):
            verify.validate_capability_map(self.matrix, value)

    def test_unproven_production_caller_is_rejected(self) -> None:
        value = deepcopy(self.capability_map)
        value["entries"][0]["productionCaller"] = "unproven-product"
        with self.assertRaises(verify.VerificationError):
            verify.validate_capability_map(self.matrix, value)

    def test_frozen_wire_vector_is_self_consistent(self) -> None:
        verify.validate_wire_vector()

    def test_source_receipt_preserves_scope_and_nonclaims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            verify.write_source_receipt(
                output, verify.git_value("rev-parse", "HEAD")
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["moduleCoverage"], 7)
        self.assertEqual(receipt["capabilityCoverage"], 21)
        self.assertEqual(
            receipt["currentImplementationTruth"], "source_and_test_anchored"
        )
        self.assertEqual(receipt["targetArchitectureImplementation"], "partial")
        self.assertEqual(receipt["externalAcceptance"], "not_claimed")


if __name__ == "__main__":
    unittest.main()
