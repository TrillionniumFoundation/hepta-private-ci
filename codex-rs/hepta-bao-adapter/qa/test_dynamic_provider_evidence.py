from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("verify_dynamic_provider_evidence.py")
SPEC = importlib.util.spec_from_file_location("verify_dynamic_provider_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA = "a" * 40
DIGEST = "b" * 64


def valid_receipt() -> dict:
    return {
        "schema": MODULE.SCHEMA,
        "sourceHeadSha": SHA,
        "sourceTreeSha": "c" * 40,
        "providerProduct": "OpenBao",
        "providerVersion": "2.6.2",
        "syntheticService": False,
        "adapterExercised": True,
        "secretMaterialRetained": False,
        "scenarios": {
            name: {"passed": True, "evidenceSha256": DIGEST}
            for name in MODULE.REQUIRED_SCENARIOS
        },
        "independentReviewers": [
            {"role": role, "principal": f"reviewer-{index}", "attestationSha256": DIGEST}
            for index, role in enumerate(sorted(MODULE.REQUIRED_REVIEW_ROLES))
        ],
        "signedAttestation": True,
        "dynamicLeaseExecutionProved": True,
        "productionAuthority": False,
    }


class DynamicProviderEvidenceTests(unittest.TestCase):
    def test_complete_real_service_receipt_passes(self) -> None:
        qualified, errors = MODULE.evaluate_receipt(valid_receipt(), SHA)
        self.assertTrue(qualified)
        self.assertEqual(errors, [])

    def test_synthetic_service_cannot_qualify(self) -> None:
        receipt = valid_receipt()
        receipt["syntheticService"] = True
        receipt["dynamicLeaseExecutionProved"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("synthetic" in error for error in errors))

    def test_direct_api_probe_without_adapter_cannot_qualify(self) -> None:
        receipt = valid_receipt()
        receipt["adapterExercised"] = False
        receipt["dynamicLeaseExecutionProved"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("adapter" in error for error in errors))

    def test_missing_crash_reconciliation_scenario_fails(self) -> None:
        receipt = valid_receipt()
        del receipt["scenarios"]["restart_query_reconcile"]
        receipt["dynamicLeaseExecutionProved"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("scenario set" in error for error in errors))

    def test_dynamic_evidence_never_grants_production_authority(self) -> None:
        receipt = valid_receipt()
        receipt["productionAuthority"] = True
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("production authority" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
