"""Closed-world tests for Lane A implementation truth."""

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

    def test_exact_repository_truth_is_valid(self) -> None:
        verify.validate_matrix(self.matrix)

    def test_closed_world_module_set(self) -> None:
        self.assertEqual(
            [row["module"] for row in self.matrix["modules"]],
            verify.EXPECTED_MODULES,
        )
        self.assertEqual(self.matrix["moduleCoverage"], 7)

    def test_operations_cannot_claim_unimplemented_durability(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][3]["states"]["durability"] = "durable"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_authbus_cannot_claim_policy_or_quota_service(self) -> None:
        value = deepcopy(self.matrix)
        value["modules"][5]["currentCapabilities"].append("quota registry")
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_repository_cannot_self_grant_acceptance(self) -> None:
        value = deepcopy(self.matrix)
        value["closure"]["externalAcceptance"] = "closed"
        with self.assertRaises(verify.VerificationError):
            verify.validate_matrix(value)

    def test_current_and_target_capabilities_are_disjoint(self) -> None:
        for row in self.matrix["modules"]:
            self.assertFalse(set(row["currentCapabilities"]) & set(row["targetOnlyCapabilities"]))

    def test_receipt_preserves_non_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            verify.write_receipt(output, verify.git_value("rev-parse", "HEAD"))
            receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["moduleCoverage"], 7)
        self.assertEqual(receipt["currentImplementationTruth"], "closed")
        self.assertEqual(receipt["productionImplementation"], "not_claimed")
        self.assertEqual(receipt["externalAcceptance"], "not_claimed")


if __name__ == "__main__":
    unittest.main()
