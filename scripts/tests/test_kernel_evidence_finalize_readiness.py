from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import kernel_evidence_finalize_readiness as finalize


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FinalizeReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity = {
            "source_head_sha": "1" * 40,
            "source_head_tree": "2" * 40,
            "base_sha": "3" * 40,
            "deterministic_merge_sha": "4" * 40,
            "github_synthetic_merge_sha": "5" * 40,
            "workflow_sha": "6" * 40,
            "final_merge_sha": None,
            "workflow_run_id": "123",
            "workflow_run_attempt": "1",
            "runner_image": "runner",
            "target_triple": "target",
        }
        self.manifest_path = self.root / "preliminary.json"
        self.runtime_path = self.root / "status.json"
        self.audit_path = self.root / "audit.json"
        self.output_path = self.root / "final.json"
        self._write_fixture(audit_passed=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self, *, audit_passed: bool) -> None:
        manifest = {
            "schema_version": 2,
            "module": "kernel.evidence",
            **self.identity,
            "artifact_hashes": {},
            "status_identity": {"runtime": {"present": True, "exact": True}},
            "readiness": {
                "repository_controlled_ready": True,
                "local_integrity_ready": True,
                "authenticated_frontier_protocol_ready": True,
                "final_merge_requalified": False,
                "authenticated_frontier_authority_ready": False,
                "external_rollback_anchor_ready": False,
                "independent_acceptance": False,
                "operator_activation": False,
                "production_activation": False,
                "promotion_approved": False,
                "release_approved": False,
            },
            "blockers": ["real_merge_sha_not_requalified"],
            "authority": {},
        }
        runtime = {
            "asOfCommit": self.identity["source_head_sha"],
            "asOfTree": self.identity["source_head_tree"],
            "baseSha": self.identity["base_sha"],
            "deterministicMergeSha": self.identity["deterministic_merge_sha"],
            "githubSyntheticMergeSha": self.identity["github_synthetic_merge_sha"],
            "workflowSha": self.identity["workflow_sha"],
            "finalMergeSha": self.identity["final_merge_sha"],
            "workflowRunId": self.identity["workflow_run_id"],
            "workflowRunAttempt": self.identity["workflow_run_attempt"],
            "runnerImage": self.identity["runner_image"],
            "targetTriple": self.identity["target_triple"],
            "repositoryControlledReady": True,
            "authenticatedFrontierProtocolQualified": True,
            "finalMergeRequalified": False,
        }
        audit_identity = {
            "sourceHeadSha": self.identity["source_head_sha"],
            "sourceHeadTree": self.identity["source_head_tree"],
            "baseSha": self.identity["base_sha"],
            "deterministicMergeSha": self.identity["deterministic_merge_sha"],
            "githubSyntheticMergeSha": self.identity["github_synthetic_merge_sha"],
            "workflowSha": self.identity["workflow_sha"],
            "finalMergeSha": self.identity["final_merge_sha"],
            "workflowRunId": self.identity["workflow_run_id"],
            "workflowRunAttempt": self.identity["workflow_run_attempt"],
            "runnerImage": self.identity["runner_image"],
            "targetTriple": self.identity["target_triple"],
        }
        audit = {
            "schemaVersion": 1,
            "module": "kernel.evidence",
            "receiptKind": "readiness_receipt_audit",
            "identity": audit_identity,
            "passed": audit_passed,
            "errors": [] if audit_passed else ["tampered log"],
        }
        write_json(self.manifest_path, manifest)
        write_json(self.runtime_path, runtime)
        write_json(self.audit_path, audit)

    def test_passed_audit_preserves_repository_readiness(self) -> None:
        result = finalize.finalize(
            self.manifest_path, self.runtime_path, self.audit_path, self.output_path
        )
        self.assertTrue(result["readiness"]["receipt_audit_qualified"])
        self.assertTrue(result["readiness"]["repository_controlled_ready"])
        runtime = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        self.assertTrue(runtime["receiptAuditQualified"])
        self.assertEqual(
            result["status_identity"]["runtime"]["sha256"],
            hashlib.sha256(self.runtime_path.read_bytes()).hexdigest(),
        )

    def test_failed_audit_forces_aggregate_readiness_false(self) -> None:
        self._write_fixture(audit_passed=False)
        result = finalize.finalize(
            self.manifest_path, self.runtime_path, self.audit_path, self.output_path
        )
        self.assertFalse(result["readiness"]["receipt_audit_qualified"])
        self.assertFalse(result["readiness"]["repository_controlled_ready"])
        self.assertFalse(result["readiness"]["local_integrity_ready"])
        self.assertIn("receipt_audit", result["blockers"])
        runtime = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        self.assertFalse(runtime["repositoryControlledReady"])
        self.assertFalse(runtime["authenticatedFrontierProtocolQualified"])

    def test_identity_mismatch_fails_closed(self) -> None:
        audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
        audit["identity"]["workflowRunAttempt"] = "2"
        write_json(self.audit_path, audit)
        result = finalize.finalize(
            self.manifest_path, self.runtime_path, self.audit_path, self.output_path
        )
        self.assertFalse(result["readiness"]["receipt_audit_qualified"])
        self.assertTrue(
            any("workflowRunAttempt" in error for error in result["receipt_audit"]["errors"])
        )


if __name__ == "__main__":
    unittest.main()
