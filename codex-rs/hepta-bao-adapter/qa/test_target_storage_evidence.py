from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("verify_target_storage_evidence.py")
SPEC = importlib.util.spec_from_file_location("verify_target_storage_evidence", MODULE_PATH)
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
        "targetId": "prod-jp-a-secrets-volume-01",
        "platform": "target-platform",
        "nodeType": "dedicated-stateful-node",
        "volumeType": "local-persistent-ssd",
        "filesystem": "ext4",
        "databasePath": "/var/lib/hepta/secrets/owner.sqlite3",
        "mountOptions": ["rw", "relatime"],
        "tests": {
            name: {"passed": True, "evidenceSha256": DIGEST}
            for name in MODULE.REQUIRED_TESTS
        },
        "independentReviewers": [
            {"role": role, "principal": f"reviewer-{index}", "attestationSha256": DIGEST}
            for index, role in enumerate(sorted(MODULE.REQUIRED_REVIEW_ROLES))
        ],
        "signedAttestation": True,
        "operatorAccepted": True,
        "targetStorageProfileQualified": True,
    }


class TargetStorageEvidenceTests(unittest.TestCase):
    def test_complete_independent_exact_candidate_receipt_passes(self) -> None:
        qualified, errors = MODULE.evaluate_receipt(valid_receipt(), SHA)
        self.assertTrue(qualified)
        self.assertEqual(errors, [])

    def test_cross_candidate_receipt_fails(self) -> None:
        qualified, errors = MODULE.evaluate_receipt(valid_receipt(), "d" * 40)
        self.assertFalse(qualified)
        self.assertTrue(any("exact candidate" in error for error in errors))

    def test_ci_local_volume_cannot_qualify(self) -> None:
        receipt = valid_receipt()
        receipt["targetId"] = "github-runner-local"
        receipt["targetStorageProfileQualified"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("CI-local" in error for error in errors))

    def test_missing_power_loss_evidence_fails(self) -> None:
        receipt = valid_receipt()
        receipt["tests"]["power_loss"]["passed"] = False
        receipt["targetStorageProfileQualified"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("power_loss" in error for error in errors))

    def test_review_roles_must_be_independent(self) -> None:
        receipt = valid_receipt()
        for reviewer in receipt["independentReviewers"]:
            reviewer["principal"] = "same-person"
        receipt["targetStorageProfileQualified"] = False
        qualified, errors = MODULE.evaluate_receipt(receipt, SHA)
        self.assertFalse(qualified)
        self.assertTrue(any("distinct" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
