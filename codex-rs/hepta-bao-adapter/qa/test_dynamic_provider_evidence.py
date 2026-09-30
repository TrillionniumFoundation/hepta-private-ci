from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_complete_claim_structure_does_not_authenticate_real_execution(self) -> None:
        complete, structure_errors = MODULE.evaluate_structure(valid_receipt(), SHA)
        self.assertTrue(complete)
        self.assertEqual(structure_errors, [])
        qualified, errors = MODULE.evaluate_receipt(valid_receipt(), SHA)
        self.assertFalse(qualified)
        self.assertEqual(errors, [MODULE.AUTHENTICATION_BLOCKER])

    def test_complete_self_authored_claim_cannot_pass_require_qualified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps(valid_receipt()), encoding="utf-8")
            output = root / "gate.json"
            args = ["verify_dynamic_provider_evidence.py", "--receipt", str(receipt_path),
                    "--expected-source-sha", SHA, "--output", str(output)]
            for required, expected_code in ((False, 0), (True, 1)):
                with self.subTest(required=required):
                    with patch.object(sys, "argv", args + (["--require-qualified"] if required else [])):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(MODULE.main(), expected_code)
                    status = json.loads(output.read_text(encoding="utf-8"))
                    self.assertTrue(status["receiptPresent"])
                    self.assertTrue(status["receiptStructureComplete"])
                    self.assertFalse(status["independentAuthenticationVerified"])
                    self.assertFalse(status["dynamicLeaseExecutionProved"])
                    self.assertEqual(status["validationReasons"], [MODULE.AUTHENTICATION_BLOCKER])

    def test_zero_candidate_tree_and_evidence_digests_fail_structure(self) -> None:
        for field in ("sourceHeadSha", "sourceTreeSha", "evidenceSha256", "attestationSha256"):
            with self.subTest(field=field):
                receipt = valid_receipt()
                if field == "evidenceSha256":
                    receipt["scenarios"]["dynamic_issue"][field] = "0" * 64
                elif field == "attestationSha256":
                    receipt["independentReviewers"][0][field] = "0" * 64
                else:
                    receipt[field] = "0" * 40
                complete, errors = MODULE.evaluate_structure(receipt, SHA)
                self.assertFalse(complete)
                self.assertTrue(errors)

    def test_principal_whitespace_cannot_create_distinct_reviewers(self) -> None:
        receipt = valid_receipt()
        receipt["independentReviewers"][1]["principal"] = (
            " " + receipt["independentReviewers"][0]["principal"] + " "
        )
        complete, errors = MODULE.evaluate_structure(receipt, SHA)
        self.assertFalse(complete)
        self.assertTrue(any("distinct" in error for error in errors))

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
