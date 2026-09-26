import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "kernel_evidence_status.py"
SPEC = importlib.util.spec_from_file_location("kernel_evidence_status", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def base_status():
    return {
        "schema": "hepta.kernel-evidence-status-source.v1",
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "asOfCommit": "a" * 40,
        "asOfTree": "b" * 40,
        "workflowRunId": None,
        "artifactDigest": None,
        "exactSourceQualified": False,
        "mergeCandidateQualified": False,
        "independentAcceptance": False,
        "externalFrontierActive": False,
        "backupRestoreDrilled": False,
        "canaryAccepted": False,
        "releaseApproved": False,
        "sourcePaths": ["codex-rs/hepta-evidence/src/lib.rs"],
        "capabilities": {key: False for key, _ in MODULE.CAPABILITIES},
        "evidenceReceipts": {},
        "claimBoundary": {
            "repositoryImplementationDoesNotProveDeployment": True,
            "workflowReceiptDoesNotGrantRelease": True,
            "externalAuthorityRequiredForAcceptance": True,
        },
    }


def receipt(status):
    return {
        "sha256": "c" * 64,
        "issuerPrincipalId": "issuer:independent-acceptance",
        "candidateCommit": status["asOfCommit"],
        "candidateTree": status["asOfTree"],
        "observedAt": "2026-09-26T00:00:00Z",
    }


class KernelEvidenceStatusTests(unittest.TestCase):
    def test_unqualified_source_is_valid_without_persistent_workflow_authority(self):
        MODULE.validate_status(base_status(), check_git=False)

    def test_true_external_gate_requires_a_bound_receipt(self):
        status = base_status()
        status["exactSourceQualified"] = True
        status["mergeCandidateQualified"] = True
        status["workflowRunId"] = "123"
        status["artifactDigest"] = "d" * 64
        status["independentAcceptance"] = True
        with self.assertRaisesRegex(ValueError, "requires an evidence receipt"):
            MODULE.validate_status(status, check_git=False)
        status["evidenceReceipts"]["independentAcceptance"] = receipt(status)
        MODULE.validate_status(status, check_git=False)

    def test_release_cannot_skip_frontier_backup_and_canary_gates(self):
        status = base_status()
        status["releaseApproved"] = True
        status["evidenceReceipts"]["releaseApproved"] = receipt(status)
        with self.assertRaisesRegex(ValueError, "releaseApproved"):
            MODULE.validate_status(status, check_git=False)

    def test_one_principal_receipt_is_bound_to_the_source_anchor(self):
        status = base_status()
        status["exactSourceQualified"] = True
        status["mergeCandidateQualified"] = True
        status["workflowRunId"] = "123"
        status["artifactDigest"] = "d" * 64
        status["externalFrontierActive"] = True
        bound = receipt(status)
        bound["candidateCommit"] = "e" * 40
        status["evidenceReceipts"]["externalFrontierActive"] = bound
        with self.assertRaisesRegex(ValueError, "not bound"):
            MODULE.validate_status(status, check_git=False)

    def test_projection_replaces_exactly_one_generated_block(self):
        status = base_status()
        block = MODULE.render_block(status)
        original = "# Document\n\nHand-written body.\n"
        projected = MODULE.project(original, block)
        self.assertIn(MODULE.STATUS_BEGIN, projected)
        self.assertEqual(projected.count(MODULE.STATUS_BEGIN), 1)
        self.assertEqual(MODULE.project(projected, block), projected)

    def test_capability_inventory_is_closed_world(self):
        status = base_status()
        status["capabilities"]["inventedCapability"] = True
        with self.assertRaisesRegex(ValueError, "closed-world"):
            MODULE.validate_status(status, check_git=False)


if __name__ == "__main__":
    unittest.main()
