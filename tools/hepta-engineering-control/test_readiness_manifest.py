from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import unittest

from control_engineering_v2 import HmacTrustStore, semantic_digest
from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.key_custody_continuity import (
    CustodiedKeyBinding,
    KeyCustodyContinuityReceipt,
)
from control_engineering_v2.readiness_manifest import (
    ACCEPTANCE_SCHEMA,
    ExternalAcceptanceReceipt,
    build_canonical_readiness_manifest,
    verify_canonical_readiness_manifest,
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class CanonicalReadinessManifestTests(unittest.TestCase):
    now = 10_000_000
    repository = "TrillionniumFoundation/hepta-private-ci"
    workflow_sha = "9" * 40
    source_sha = "1" * 40
    source_tree = "2" * 40
    base_sha = "3" * 40
    merge_sha = "4" * 40
    merge_tree = "5" * 40
    required_jobs = (
        "control.engineering canonical lane (source-head)",
        "control.engineering canonical lane (base-merge)",
    )

    def setUp(self) -> None:
        self.trust = HmacTrustStore(
            {
                ("independent_evaluator", "review-key"): b"review",
                ("integration_observer", "integration-key"): b"integration",
                ("deployment_authority", "deployment-key"): b"deployment",
                ("deployment_authority", "rollback-key"): b"rollback",
                ("audit_anchor_service", "audit-key"): b"audit",
                ("key_custody_authority", "custody-key"): b"custody",
            }
        )

    def pair(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": "hepta.control-engineering-product-receipt-pair.v3",
            "repository": self.repository,
            "repositoryId": 123,
            "runId": 456,
            "runAttempt": 2,
            "pullRequestNumber": 1001,
            "sourceSha": self.source_sha,
            "sourceTree": self.source_tree,
            "baseSha": self.base_sha,
            "mergeSha": self.merge_sha,
            "mergeTree": self.merge_tree,
            "sourceProductReceiptDigest": "a" * 64,
            "mergeProductReceiptDigest": "b" * 64,
            "canonicalWorkPackageBlobOid": "6" * 40,
            "canonicalWorkPackageDigest": "c" * 64,
            "runtimeAuthority": False,
            "mergeAuthority": False,
            "releaseAuthority": False,
        }
        value["readinessReceiptSetDigest"] = digest(
            {"baseMerge": "b" * 64, "sourceHead": "a" * 64}
        )
        value["pairDigest"] = digest(value)
        return value

    def jobs(self, *, conclusion: str = "success", attempt: int = 2) -> dict[str, object]:
        return {
            "runId": 456,
            "runAttempt": attempt,
            "workflowSha": self.workflow_sha,
            "jobs": [
                {
                    "id": index + 10,
                    "name": name,
                    "status": "completed",
                    "conclusion": conclusion,
                    "started_at": "2026-09-30T00:00:00Z",
                    "completed_at": "2026-09-30T00:01:00Z",
                    "runner_name": "GitHub Actions 1",
                    "runner_group_id": 1,
                }
                for index, name in enumerate(self.required_jobs)
            ],
        }

    @staticmethod
    def runner() -> dict[str, object]:
        return {
            "runnerImage": "ubuntu-24.04@20260920.314.1",
            "runnerImageDigest": "d" * 64,
            "toolchainDigest": "e" * 64,
            "targetTriple": "x86_64-unknown-linux-gnu",
            "environmentAllowlistDigest": "f" * 64,
            "sbomDigest": "1" * 64,
            "isolationProfileDigest": "2" * 64,
        }

    def evidence(self) -> dict[str, object]:
        return {
            "schemaVersion": 10,
            "sourceTreeSha1": self.source_tree,
            "sourceTreeHash": "3" * 64,
            "migrationHash": "4" * 64,
            "testSetHash": "5" * 64,
            "implementationMapHash": "6" * 64,
            "documentationHash": "7" * 64,
            "qualificationProfileHash": "8" * 64,
        }

    @staticmethod
    def artifacts() -> dict[str, object]:
        return {
            "source-product-receipt": "9" * 64,
            "merge-product-receipt": "a" * 64,
            "strong-sandbox-profile": "b" * 64,
        }

    def acceptance(
        self,
        kind: str,
        issuer: str,
        identity: str,
    ) -> ExternalAcceptanceReceipt:
        value = ExternalAcceptanceReceipt(
            schema=ACCEPTANCE_SCHEMA,
            kind=kind,
            repository=self.repository,
            source_sha=self.source_sha,
            source_tree=self.source_tree,
            base_sha=self.base_sha,
            merge_sha=self.merge_sha,
            merge_tree=self.merge_tree,
            workflow_sha=self.workflow_sha,
            run_id=456,
            run_attempt=2,
            evidence_digest=(kind[0] if kind[0] in "abcdef" else "c") * 64,
            issuer=issuer,
            signing_identity=identity,
            observed_unix_ns=self.now - 100,
            expires_unix_ns=self.now + 10_000,
            accepted=True,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    @staticmethod
    def custody_keys() -> tuple[CustodiedKeyBinding, ...]:
        roles = (
            "source_authority",
            "ci_executor",
            "independent_evaluator",
            "engineering_evidence_binder",
        )
        return tuple(
            CustodiedKeyBinding(
                role=role,
                provider="kms-prod",
                key_id=f"key-{index}",
                algorithm="ed25519",
                subject_signing_identity="review-key" if role == "independent_evaluator" else f"subject-{index}",
                public_key_digest=f"{index + 1:x}" * 64,
                attestation_digest=f"{index + 5:x}" * 64,
                hardware_backed=True,
                external_to_engineering=True,
            )
            for index, role in enumerate(roles)
        )

    def custody(self) -> KeyCustodyContinuityReceipt:
        value = KeyCustodyContinuityReceipt(
            repository=self.repository,
            source_sha=self.source_sha,
            merge_sha=self.merge_sha,
            rotation_epoch=1,
            rotation_state="active",
            previous_set_digest="0" * 64,
            revocation_frontier_digest="c" * 64,
            external_audit_anchor_digest="d" * 64,
            current_keys=self.custody_keys(),
            retiring_keys=(),
            dual_window_expires_unix_ns=0,
            issuer="key_custody_authority",
            signing_identity="custody-key",
            observed_unix_ns=self.now - 100,
            expires_unix_ns=self.now + 10_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def build(self, **kwargs: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "workflow_sha": self.workflow_sha,
            "required_job_names": self.required_jobs,
            "now_ns": self.now,
        }
        arguments.update(kwargs)
        return build_canonical_readiness_manifest(
            self.pair(),
            self.jobs(),
            self.runner(),
            self.evidence(),
            self.artifacts(),
            **arguments,
        )

    def test_internal_success_does_not_manufacture_external_acceptance(self) -> None:
        manifest = self.build()
        self.assertTrue(manifest["internalEvidenceReady"])
        self.assertFalse(manifest["mergeReady"])
        self.assertFalse(manifest["productionQualified"])
        self.assertIn("independent_review_missing", manifest["blockers"])
        self.assertIn("key_custody_continuity_missing", manifest["blockers"])
        self.assertRegex(verify_canonical_readiness_manifest(manifest, now_ns=self.now), r"^[0-9a-f]{64}$")

    def test_failed_cancelled_or_cross_attempt_jobs_fail_closed(self) -> None:
        failed = build_canonical_readiness_manifest(
            self.pair(),
            self.jobs(conclusion="cancelled"),
            self.runner(),
            self.evidence(),
            self.artifacts(),
            workflow_sha=self.workflow_sha,
            required_job_names=self.required_jobs,
            now_ns=self.now,
        )
        self.assertFalse(failed["internalEvidenceReady"])
        self.assertFalse(failed["mergeReady"])
        self.assertFalse(failed["productionQualified"])
        self.assertIn(
            "required_job_cancelled:" + self.required_jobs[0],
            failed["blockers"],
        )
        with self.assertRaisesRegex(EngineeringError, "readiness_job_attempt_splice"):
            build_canonical_readiness_manifest(
                self.pair(),
                self.jobs(attempt=1),
                self.runner(),
                self.evidence(),
                self.artifacts(),
                workflow_sha=self.workflow_sha,
                required_job_names=self.required_jobs,
                now_ns=self.now,
            )

    def test_full_external_receipt_set_and_custody_can_qualify(self) -> None:
        receipts = (
            self.acceptance("independent_review", "independent_evaluator", "review-key"),
            self.acceptance("external_integration", "integration_observer", "integration-key"),
            self.acceptance("deployment_acceptance", "deployment_authority", "deployment-key"),
            self.acceptance("rollback_rehearsal", "deployment_authority", "rollback-key"),
            self.acceptance("external_audit_anchor", "audit_anchor_service", "audit-key"),
        )
        manifest = self.build(
            acceptance_receipts=receipts,
            custody_receipt=self.custody(),
            trust_store=self.trust,
        )
        self.assertTrue(manifest["internalEvidenceReady"])
        self.assertTrue(manifest["mergeReady"])
        self.assertTrue(manifest["productionQualified"])
        self.assertEqual(manifest["blockers"], [])
        verify_canonical_readiness_manifest(manifest, now_ns=self.now)

    def test_exceptions_block_merge_and_production_even_with_signed_evidence(self) -> None:
        review = self.acceptance(
            "independent_review",
            "independent_evaluator",
            "review-key",
        )
        manifest = self.build(
            acceptance_receipts=(review,),
            trust_store=self.trust,
            exception_records=(
                {
                    "exceptionId": "operator-override-1",
                    "reason": "manual bypass requested",
                    "receiptDigest": "e" * 64,
                },
            ),
        )
        self.assertFalse(manifest["internalEvidenceReady"])
        self.assertFalse(manifest["mergeReady"])
        self.assertFalse(manifest["productionQualified"])
        self.assertIn("exception_records_present", manifest["blockers"])
        verify_canonical_readiness_manifest(manifest, now_ns=self.now)

    def test_manifest_tampering_is_rejected(self) -> None:
        manifest = self.build()
        manifest["productionQualified"] = True
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_digest_mismatch"):
            verify_canonical_readiness_manifest(manifest, now_ns=self.now)

    def test_rehashed_missing_jobs_cannot_retain_internal_success(self) -> None:
        manifest = self.build()
        manifest["job_ids"] = {}
        manifest["required_check_results"] = {}
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = digest(manifest)
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_required_jobs"):
            verify_canonical_readiness_manifest(manifest, now_ns=self.now)

    def test_rehashed_failed_job_cannot_retain_internal_success(self) -> None:
        manifest = self.build()
        name = self.required_jobs[0]
        manifest["job_ids"][name]["conclusion"] = "failure"
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = digest(manifest)
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_internal_projection"):
            verify_canonical_readiness_manifest(manifest, now_ns=self.now)

    def test_retained_manifest_expires_and_consumer_pins_job_policy(self) -> None:
        manifest = self.build()
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_expired"):
            verify_canonical_readiness_manifest(manifest, now_ns=manifest["evidence_expiry"])
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_job_policy_mismatch"):
            verify_canonical_readiness_manifest(
                manifest, now_ns=self.now, expected_required_job_names=("unrelated-job",)
            )

    def test_one_job_id_cannot_satisfy_two_required_jobs(self) -> None:
        jobs = self.jobs()
        jobs["jobs"][1]["id"] = jobs["jobs"][0]["id"]
        with self.assertRaisesRegex(EngineeringError, "readiness_job_identity_collision"):
            build_canonical_readiness_manifest(
                self.pair(), jobs, self.runner(), self.evidence(), self.artifacts(),
                workflow_sha=self.workflow_sha, required_job_names=self.required_jobs,
                now_ns=self.now,
            )

    def test_acceptance_stream_is_consumed_only_to_limit(self) -> None:
        consumed = []
        def receipts():
            for index in range(1000):
                consumed.append(index)
                yield None
        with self.assertRaisesRegex(EngineeringError, "readiness_acceptance_limit"):
            self.build(acceptance_receipts=receipts())
        self.assertEqual(len(consumed), 17)

    def test_valid_review_signature_must_use_custodied_evaluator(self) -> None:
        custody = self.custody()
        keys = tuple(
            replace(key, subject_signing_identity="unrelated-review-key")
            if key.role == "independent_evaluator" else key
            for key in custody.current_keys
        )
        custody = replace(custody, current_keys=keys, signature="")
        custody = replace(custody, signature=self.trust.sign(
            custody, custody.issuer, custody.signing_identity
        ))
        with self.assertRaisesRegex(EngineeringError, "readiness_review_custody_mismatch"):
            self.build(
                acceptance_receipts=(self.acceptance(
                    "independent_review", "independent_evaluator", "review-key"
                ),), custody_receipt=custody, trust_store=self.trust,
            )

    def rotating_custody(self, *, retiring_reviewer):
        previous = self.custody()
        if not retiring_reviewer:
            previous = replace(previous, current_keys=tuple(
                replace(key, subject_signing_identity="old-review-key")
                if key.role == "independent_evaluator" else key
                for key in previous.current_keys
            ), signature="")
            previous = replace(previous, signature=self.trust.sign(
                previous, previous.issuer, previous.signing_identity
            ))
        current = tuple(replace(
            key, key_id="rotated-" + key.key_id,
            subject_signing_identity=(
                "review-key" if key.role == "independent_evaluator" and not retiring_reviewer
                else "rotated-" + key.subject_signing_identity
            ), public_key_digest=semantic_digest({"rotatedKey": key.role}),
        ) for key in previous.current_keys)
        receipt = replace(
            previous, rotation_epoch=2, rotation_state="dual_window",
            previous_set_digest=semantic_digest(asdict(previous)),
            current_keys=current,
            retiring_keys=tuple(sorted(previous.current_keys, key=lambda key: key.role)),
            dual_window_expires_unix_ns=self.now + 100, signature="",
        )
        receipt = replace(receipt, signature=self.trust.sign(
            receipt, receipt.issuer, receipt.signing_identity
        ))
        return previous, receipt

    def test_retiring_reviewer_limits_retained_manifest_to_dual_window(self) -> None:
        previous, custody = self.rotating_custody(retiring_reviewer=True)
        manifest = self.build(
            acceptance_receipts=(self.acceptance(
                "independent_review", "independent_evaluator", "review-key"
            ),), custody_receipt=custody, previous_custody_receipt=previous,
            trust_store=self.trust,
        )
        self.assertTrue(manifest["mergeReady"])
        self.assertEqual(manifest["evidence_expiry"], custody.dual_window_expires_unix_ns)
        verify_canonical_readiness_manifest(
            manifest, now_ns=custody.dual_window_expires_unix_ns - 1
        )
        with self.assertRaisesRegex(EngineeringError, "readiness_manifest_expired"):
            verify_canonical_readiness_manifest(
                manifest, now_ns=custody.dual_window_expires_unix_ns
            )

    def test_current_reviewer_does_not_inherit_retiring_key_expiry(self) -> None:
        previous, custody = self.rotating_custody(retiring_reviewer=False)
        manifest = self.build(
            acceptance_receipts=(self.acceptance(
                "independent_review", "independent_evaluator", "review-key"
            ),), custody_receipt=custody, previous_custody_receipt=previous,
            trust_store=self.trust,
        )
        self.assertTrue(manifest["mergeReady"])
        self.assertEqual(manifest["evidence_expiry"], custody.expires_unix_ns)
        verify_canonical_readiness_manifest(
            manifest, now_ns=custody.dual_window_expires_unix_ns
        )

    def test_source_commit_cannot_impersonate_synthetic_merge(self) -> None:
        pair = self.pair()
        pair["mergeSha"] = pair["sourceSha"]
        pair.pop("pairDigest")
        pair["pairDigest"] = digest(pair)
        with self.assertRaisesRegex(EngineeringError, "readiness_pair_merge_identity"):
            build_canonical_readiness_manifest(
                pair, self.jobs(), self.runner(), self.evidence(), self.artifacts(),
                workflow_sha=self.workflow_sha, required_job_names=self.required_jobs,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
