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
    SandboxReceipt,
    SealedCandidateEvidence,
    bind_candidate_evidence,
    record_integration_decision,
    request_independent_review,
    semantic_digest,
    verify_sealed_candidate_evidence,
)


class SealedEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 500
        self.base_commit = "a" * 40
        self.tree = "b" * 40
        self.trust = HmacTrustStore(
            {
                ("ci_executor", "ci-key"): b"ci-secret",
                ("engineering_evidence_binder", "binder-key"): b"binder-secret",
            }
        )
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
            (("mandatory-check", 0),),
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
        binding = CandidateEvidenceBindingReceipt(
            self.candidate.candidate_id,
            self.candidate.semantic_digest,
            self.sandbox_digest,
            self.base_commit,
            self.evidence.evidence_digest,
            semantic_digest(asdict(self.source)),
            semantic_digest(asdict(self.merge)),
            "ci_executor",
            "ci-key",
            120,
            900,
        )
        self.binding = replace(
            binding,
            signature=self.trust.sign(binding, binding.issuer, binding.signing_identity),
        )

    def sealed(self) -> SealedCandidateEvidence:
        return bind_candidate_evidence(
            self.candidate,
            self.sandbox,
            self.evidence,
            self.source,
            self.merge,
            self.binding,
            self.trust,
            seal_signing_identity="binder-key",
            now_ns=self.now,
        )

    def test_direct_verified_dataclass_is_rejected_by_public_review(self) -> None:
        forged_internal = BoundEvidenceDecision(
            True,
            (),
            "e" * 64,
            self.candidate.candidate_id,
            self.candidate.semantic_digest,
            self.sandbox_digest,
            "6" * 64,
        )
        with self.assertRaisesRegex(EngineeringError, "sealed_evidence_required"):
            request_independent_review(
                self.candidate,
                forged_internal,
                "independent_evaluator",
                trust_store=self.trust,
                now_ns=self.now,
            )

    def test_direct_verified_dataclass_is_rejected_by_public_persistence(self) -> None:
        forged_internal = BoundEvidenceDecision(
            True,
            (),
            "e" * 64,
            self.candidate.candidate_id,
            self.candidate.semantic_digest,
            self.sandbox_digest,
            "6" * 64,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                with self.assertRaisesRegex(EngineeringError, "sealed_evidence_required"):
                    record_integration_decision(
                        store,
                        "decision-a",
                        forged_internal,
                        trust_store=self.trust,
                        now_ns=self.now,
                    )

    def test_valid_seal_allows_review_but_no_acceptance(self) -> None:
        sealed = self.sealed()
        verify_sealed_candidate_evidence(sealed, self.trust, now_ns=self.now)
        request = request_independent_review(
            self.candidate,
            sealed,
            "independent_evaluator",
            trust_store=self.trust,
            now_ns=self.now,
        )
        self.assertEqual(request.status, "review_requested")
        self.assertFalse(request.independent_acceptance)
        self.assertFalse(request.merge_authority)
        self.assertFalse(request.release_authority)

    def test_forged_seal_signature_is_rejected(self) -> None:
        forged = replace(self.sealed(), signature="0" * 64)
        with self.assertRaisesRegex(EngineeringError, "sealed_evidence_signature"):
            verify_sealed_candidate_evidence(forged, self.trust, now_ns=self.now)

    def test_expired_seal_is_rejected_even_with_valid_signature(self) -> None:
        sealed = self.sealed()
        expired = replace(sealed, expires_unix_ns=self.now, signature="")
        expired = replace(
            expired,
            signature=self.trust.sign(expired, expired.issuer, expired.signing_identity),
        )
        with self.assertRaisesRegex(EngineeringError, "sealed_evidence_stale"):
            verify_sealed_candidate_evidence(expired, self.trust, now_ns=self.now)

    def test_seal_and_candidate_binding_survive_reopen(self) -> None:
        sealed = self.sealed()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(database) as store:
                self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 5)
                record_integration_decision(
                    store,
                    "decision-a",
                    sealed,
                    trust_store=self.trust,
                    now_ns=self.now,
                )
                binding = store.integration_decision_binding("decision-a")
                seal = store.integration_decision_seal("decision-a")
                self.assertEqual(binding["candidateId"], self.candidate.candidate_id)
                self.assertEqual(seal["sealedEvidenceDigest"], sealed.evidence_digest)
            with EngineeringStore(database) as reopened:
                self.assertEqual(reopened.integration_decision_binding("decision-a"), binding)
                self.assertEqual(reopened.integration_decision_seal("decision-a"), seal)

    def test_exact_sealed_retry_is_idempotent(self) -> None:
        sealed = self.sealed()
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                record_integration_decision(
                    store,
                    "decision-a",
                    sealed,
                    trust_store=self.trust,
                    now_ns=self.now,
                )
                record_integration_decision(
                    store,
                    "decision-a",
                    sealed,
                    trust_store=self.trust,
                    now_ns=self.now + 1,
                )
                self.assertEqual(
                    store.integration_decision_seal("decision-a")["recordedUnixNs"],
                    self.now,
                )

    def test_seal_cannot_be_replayed_under_another_decision(self) -> None:
        sealed = self.sealed()
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                record_integration_decision(
                    store,
                    "decision-a",
                    sealed,
                    trust_store=self.trust,
                    now_ns=self.now,
                )
                with self.assertRaisesRegex(EngineeringError, "sealed_evidence_replay"):
                    record_integration_decision(
                        store,
                        "decision-b",
                        sealed,
                        trust_store=self.trust,
                        now_ns=self.now + 1,
                    )

    def test_unknown_seal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                with self.assertRaisesRegex(EngineeringError, "unknown_integration_decision_seal"):
                    store.integration_decision_seal("decision-missing")


if __name__ == "__main__":
    unittest.main()
