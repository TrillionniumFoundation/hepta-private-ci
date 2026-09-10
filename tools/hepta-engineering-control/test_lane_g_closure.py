from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    BoundEvidenceDecision,
    Candidate,
    CandidateEvidenceBindingReceipt,
    EngineeringError,
    EngineeringStore,
    EvidenceDecision,
    ExecutionReceipt,
    HmacTrustStore,
    Mutation,
    OwnerConsentAttestation,
    OwnerConsentReceipt,
    SandboxReceipt,
    bind_candidate_evidence,
    prepare_assimilation_candidate,
    record_integration_decision,
    semantic_digest,
)


class PersistedDecisionClosureTests(unittest.TestCase):
    def decision(self, *, candidate_id: str = "candidate-a") -> BoundEvidenceDecision:
        return BoundEvidenceDecision(
            eligible_for_independent_review=True,
            reasons=(),
            evidence_digest="e" * 64,
            candidate_id=candidate_id,
            candidate_digest="c" * 64,
            sandbox_receipt_digest="s" * 64,
            binding_receipt_digest="b" * 64,
        )

    def test_schema_v4_and_binding_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(database) as store:
                version = store.connection.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, 4)
                record_integration_decision(
                    store,
                    "decision-a",
                    self.decision(),
                    now_ns=100,
                )
                first = store.integration_decision_binding("decision-a")
                self.assertEqual(first["candidateId"], "candidate-a")
                self.assertEqual(first["boundEvidenceDigest"], "e" * 64)
            with EngineeringStore(database) as reopened:
                second = reopened.integration_decision_binding("decision-a")
                self.assertEqual(second, first)

    def test_decision_id_cannot_be_rebound_to_another_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                record_integration_decision(
                    store,
                    "decision-a",
                    self.decision(),
                    now_ns=100,
                )
                with self.assertRaisesRegex(EngineeringError, "decision_binding_conflict"):
                    record_integration_decision(
                        store,
                        "decision-a",
                        self.decision(candidate_id="candidate-b"),
                        now_ns=101,
                    )

    def test_unknown_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                with self.assertRaisesRegex(
                    EngineeringError,
                    "unknown_integration_decision_binding",
                ):
                    store.integration_decision_binding("decision-missing")


class ReceiptFrontierClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 500
        self.base_commit = "a" * 40
        self.tree = "b" * 40
        self.trust = HmacTrustStore({("ci_executor", "ci-key"): b"ci-secret"})
        candidate = Candidate(
            "candidate-a",
            "envelope-a",
            self.base_commit,
            Mutation("no_change"),
            "c" * 64,
            "sandbox_tested",
            (),
            None,
        )
        self.sandbox = SandboxReceipt(
            candidate.candidate_id,
            self.base_commit,
            self.tree,
            self.tree,
            (("check-a", 0),),
            0,
            True,
            10,
            True,
        )
        self.sandbox_digest = semantic_digest(asdict(self.sandbox))
        self.candidate = replace(candidate, sandbox_receipt_digest=self.sandbox_digest)
        self.evidence = EvidenceDecision(True, (), "e" * 64)
        source = ExecutionReceipt(
            "source-run",
            "exact_source",
            self.base_commit,
            self.tree,
            (),
            "1" * 64,
            True,
            "ci_executor",
            "ci-key",
            100,
            1000,
        )
        merge = ExecutionReceipt(
            "merge-run",
            "synthetic_merge",
            "d" * 40,
            "f" * 40,
            ("0" * 40, self.base_commit),
            "2" * 64,
            True,
            "ci_executor",
            "ci-key",
            120,
            900,
        )
        self.source = replace(
            source,
            signature=self.trust.sign(source, source.issuer, source.signing_identity),
        )
        self.merge = replace(
            merge,
            signature=self.trust.sign(merge, merge.issuer, merge.signing_identity),
        )

    def binding(self, *, observed: int = 120, expires: int = 900):
        value = CandidateEvidenceBindingReceipt(
            self.candidate.candidate_id,
            self.candidate.semantic_digest,
            self.sandbox_digest,
            self.base_commit,
            self.evidence.evidence_digest,
            semantic_digest(asdict(self.source)),
            semantic_digest(asdict(self.merge)),
            "ci_executor",
            "ci-key",
            observed,
            expires,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_source_execution_tree_must_match_sandbox_base(self) -> None:
        wrong = replace(self.source, tree="9" * 40, signature="")
        wrong = replace(
            wrong,
            signature=self.trust.sign(wrong, wrong.issuer, wrong.signing_identity),
        )
        with self.assertRaisesRegex(EngineeringError, "source_execution_tree_mismatch"):
            bind_candidate_evidence(
                self.candidate,
                self.sandbox,
                self.evidence,
                wrong,
                self.merge,
                self.binding(),
                self.trust,
                now_ns=self.now,
            )

    def test_binding_window_cannot_escape_execution_receipts(self) -> None:
        with self.assertRaisesRegex(EngineeringError, "candidate_binding_window_escape"):
            bind_candidate_evidence(
                self.candidate,
                self.sandbox,
                self.evidence,
                self.source,
                self.merge,
                self.binding(observed=119),
                self.trust,
                now_ns=self.now,
            )


class ConsentFrontierClosureTests(unittest.TestCase):
    def test_attestation_window_cannot_escape_owner_consent(self) -> None:
        trust = HmacTrustStore({("external-owner", "owner-key"): b"owner-secret"})
        template = OwnerConsentReceipt(
            "external-owner",
            "1" * 64,
            ("query_health",),
            ("isolated-rootfs",),
            100,
            1000,
            "0" * 64,
        )
        payload = semantic_digest(
            {
                "ownerPrincipal": template.owner_principal,
                "targetIdentityDigest": template.target_identity_digest,
                "allowedOperations": tuple(sorted(template.allowed_operations)),
                "allowedRoots": tuple(sorted(template.allowed_roots)),
                "observedUnixNs": template.observed_unix_ns,
                "expiresUnixNs": template.expires_unix_ns,
            }
        )
        consent = replace(template, receipt_digest=payload)
        attestation = OwnerConsentAttestation(
            "external-owner",
            "1" * 64,
            payload,
            "external-owner",
            "owner-key",
            99,
            1000,
        )
        attestation = replace(
            attestation,
            signature=trust.sign(attestation, attestation.issuer, attestation.signing_identity),
        )
        with self.assertRaisesRegex(EngineeringError, "consent_attestation_window_escape"):
            prepare_assimilation_candidate(
                consent,
                {},
                (),
                lambda manifest, operations: None,
                trust_store=trust,
                consent_attestation=attestation,
                now_ns=500,
            )


if __name__ == "__main__":
    unittest.main()
