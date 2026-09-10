"""Schema-v5 non-forgeable evidence seal for Lane G.

A Python dataclass is not an authority capability: callers can instantiate one.
This layer therefore requires a separately authenticated evidence-binder seal at
every review and eligible-decision boundary, and persists that seal atomically
with the exact candidate binding.  It still grants no acceptance, merge,
activation, promotion, release, deployment, peer-enrollment, credential, or
runtime authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import time
from typing import Any, Mapping

from . import closure as _closure
from . import control_plane as _control
from . import facade as _facade
from . import hardening as _hardening
from .candidate import Candidate, SandboxReceipt
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_SCHEMA_VERSION = 5
_SEAL_ISSUER = "engineering_evidence_binder"

# Both earlier initializers consult these globals at call time. Raising them
# before capturing the installed schema-v4 initializer makes schema-v5 stores
# reopenable and preserves their future-version rejection.
_hardening._STORE_SCHEMA_VERSION = _SCHEMA_VERSION
_closure._FINAL_SCHEMA_VERSION = _SCHEMA_VERSION
_BASE_STORE_INIT = _control.EngineeringStore.__init__
_BASE_REQUEST_REVIEW = _hardening.hardened_request_independent_review
_BASE_RECORD_DECISION = _closure._BASE_RECORD_DECISION
_BASE_INELIGIBLE_RECORD = _closure.record_integration_decision


@dataclass(frozen=True)
class SealedCandidateEvidence:
    eligible_for_independent_review: bool
    reasons: tuple[str, ...]
    evidence_digest: str
    base_evidence_digest: str
    candidate_id: str
    candidate_digest: str
    sandbox_receipt_digest: str
    binding_receipt_digest: str
    source_execution_digest: str
    merge_execution_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    candidate_bound: bool = True
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _seal_payload(value: SealedCandidateEvidence) -> Mapping[str, object]:
    return {
        "eligibleForIndependentReview": value.eligible_for_independent_review,
        "reasons": value.reasons,
        "baseEvidenceDigest": value.base_evidence_digest,
        "candidateId": value.candidate_id,
        "candidateDigest": value.candidate_digest,
        "sandboxReceiptDigest": value.sandbox_receipt_digest,
        "bindingReceiptDigest": value.binding_receipt_digest,
        "sourceExecutionDigest": value.source_execution_digest,
        "mergeExecutionDigest": value.merge_execution_digest,
        "issuer": value.issuer,
        "signingIdentity": value.signing_identity,
        "observedUnixNs": value.observed_unix_ns,
        "expiresUnixNs": value.expires_unix_ns,
        "candidateBound": value.candidate_bound,
        "runtimeAuthority": value.runtime_authority,
        "mergeAuthority": value.merge_authority,
        "activationAuthority": value.activation_authority,
        "promotionAuthority": value.promotion_authority,
        "releaseAuthority": value.release_authority,
    }


def _checked_now(now_ns: int | None) -> int:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    return now


def _install_seal_schema(store: _control.EngineeringStore) -> None:
    row = store.connection.execute(
        "SELECT schema_version FROM engineering_schema_meta WHERE singleton=1"
    ).fetchone()
    if row is not None and int(row[0]) > _SCHEMA_VERSION:
        raise _control.EngineeringError("unsupported_future_store_schema")
    store.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS integration_decision_seals(
          decision_id TEXT PRIMARY KEY,
          seal_digest TEXT NOT NULL UNIQUE,
          sealed_evidence_digest TEXT NOT NULL UNIQUE,
          issuer TEXT NOT NULL,
          signing_identity TEXT NOT NULL,
          observed_unix_ns INTEGER NOT NULL,
          expires_unix_ns INTEGER NOT NULL,
          signature_digest TEXT NOT NULL,
          recorded_unix_ns INTEGER NOT NULL,
          semantic_digest TEXT NOT NULL,
          FOREIGN KEY(decision_id)
            REFERENCES integration_decision_bindings(decision_id)
            DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX IF NOT EXISTS idx_integration_decision_seals_identity
          ON integration_decision_seals(issuer,signing_identity,observed_unix_ns);
        """
    )
    now = time.time_ns()
    store.connection.execute(
        "UPDATE engineering_schema_meta SET schema_version=?,updated_unix_ns=? "
        "WHERE singleton=1",
        (_SCHEMA_VERSION, now),
    )
    store.connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
    store.connection.commit()


def _sealed_store_init(
    self: _control.EngineeringStore,
    database: str | Path,
    *args: Any,
    **kwargs: Any,
) -> None:
    _BASE_STORE_INIT(self, database, *args, **kwargs)
    try:
        _install_seal_schema(self)
    except BaseException:
        self.connection.close()
        raise


def verify_sealed_candidate_evidence(
    value: SealedCandidateEvidence,
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
) -> None:
    now = _checked_now(now_ns)
    if not isinstance(value, SealedCandidateEvidence):
        raise _control.EngineeringError("sealed_evidence_required")
    if value.eligible_for_independent_review is not True or value.reasons:
        raise _control.EngineeringError("sealed_evidence_not_eligible")
    if value.candidate_bound is not True:
        raise _control.EngineeringError("sealed_evidence_candidate_binding")
    for name in (
        "runtime_authority",
        "merge_authority",
        "activation_authority",
        "promotion_authority",
        "release_authority",
    ):
        if getattr(value, name) is not False:
            raise _control.EngineeringError("sealed_evidence_authority_delta")
    _control.checked_id(value.candidate_id, "candidate_id")
    for digest, label in (
        (value.evidence_digest, "sealed_evidence_digest"),
        (value.base_evidence_digest, "base_evidence_digest"),
        (value.candidate_digest, "candidate_digest"),
        (value.sandbox_receipt_digest, "sandbox_receipt_digest"),
        (value.binding_receipt_digest, "binding_receipt_digest"),
        (value.source_execution_digest, "source_execution_digest"),
        (value.merge_execution_digest, "merge_execution_digest"),
    ):
        _control.checked_sha256(digest, label)
    if value.issuer != _SEAL_ISSUER or not value.signing_identity:
        raise _control.EngineeringError("sealed_evidence_issuer_role")
    if not _hardening._valid_window(value.observed_unix_ns, value.expires_unix_ns, now):
        raise _control.EngineeringError("sealed_evidence_stale")
    if _control.semantic_digest(_seal_payload(value)) != value.evidence_digest:
        raise _control.EngineeringError("sealed_evidence_digest_mismatch")
    if not trust_store.verify(
        value,
        value.issuer,
        value.signing_identity,
        value.signature,
    ):
        raise _control.EngineeringError("sealed_evidence_signature")


def bind_candidate_evidence(
    candidate: Candidate,
    sandbox: SandboxReceipt,
    evidence: EvidenceDecision,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    binding: _hardening.CandidateEvidenceBindingReceipt,
    trust_store: HmacTrustStore,
    *,
    seal_signing_identity: str,
    now_ns: int | None = None,
) -> SealedCandidateEvidence:
    now = _checked_now(now_ns)
    bound = _closure.bind_candidate_evidence(
        candidate,
        sandbox,
        evidence,
        source_execution,
        merge_execution,
        binding,
        trust_store,
        now_ns=now,
    )
    if not seal_signing_identity:
        raise _control.EngineeringError("sealed_evidence_signing_identity")
    observed = max(
        now,
        binding.observed_unix_ns,
        source_execution.observed_unix_ns,
        merge_execution.observed_unix_ns,
    )
    expires = min(
        binding.expires_unix_ns,
        source_execution.expires_unix_ns,
        merge_execution.expires_unix_ns,
    )
    if not _hardening._valid_window(observed, expires, now):
        raise _control.EngineeringError("sealed_evidence_stale")
    unsigned = SealedCandidateEvidence(
        True,
        (),
        "0" * 64,
        bound.evidence_digest,
        candidate.candidate_id,
        candidate.semantic_digest,
        bound.sandbox_receipt_digest,
        bound.binding_receipt_digest,
        _control.semantic_digest(asdict(source_execution)),
        _control.semantic_digest(asdict(merge_execution)),
        _SEAL_ISSUER,
        seal_signing_identity,
        observed,
        expires,
    )
    digest = _control.semantic_digest(_seal_payload(unsigned))
    unsigned = SealedCandidateEvidence(
        unsigned.eligible_for_independent_review,
        unsigned.reasons,
        digest,
        unsigned.base_evidence_digest,
        unsigned.candidate_id,
        unsigned.candidate_digest,
        unsigned.sandbox_receipt_digest,
        unsigned.binding_receipt_digest,
        unsigned.source_execution_digest,
        unsigned.merge_execution_digest,
        unsigned.issuer,
        unsigned.signing_identity,
        unsigned.observed_unix_ns,
        unsigned.expires_unix_ns,
    )
    try:
        signature = trust_store.sign(unsigned, unsigned.issuer, unsigned.signing_identity)
    except (KeyError, ValueError):
        raise _control.EngineeringError("sealed_evidence_signing_key") from None
    sealed = SealedCandidateEvidence(
        unsigned.eligible_for_independent_review,
        unsigned.reasons,
        unsigned.evidence_digest,
        unsigned.base_evidence_digest,
        unsigned.candidate_id,
        unsigned.candidate_digest,
        unsigned.sandbox_receipt_digest,
        unsigned.binding_receipt_digest,
        unsigned.source_execution_digest,
        unsigned.merge_execution_digest,
        unsigned.issuer,
        unsigned.signing_identity,
        unsigned.observed_unix_ns,
        unsigned.expires_unix_ns,
        signature,
    )
    verify_sealed_candidate_evidence(sealed, trust_store, now_ns=now)
    return sealed


def request_independent_review(
    candidate: Candidate,
    evidence: SealedCandidateEvidence,
    requested_role: str,
    *,
    trust_store: HmacTrustStore,
    now_ns: int | None = None,
) -> _facade.ReviewRequest:
    now = _checked_now(now_ns)
    verify_sealed_candidate_evidence(evidence, trust_store, now_ns=now)
    if (
        candidate.state != "sandbox_tested"
        or candidate.candidate_id != evidence.candidate_id
        or candidate.semantic_digest != evidence.candidate_digest
        or candidate.sandbox_receipt_digest != evidence.sandbox_receipt_digest
    ):
        raise _control.EngineeringError("sealed_evidence_candidate_mismatch")
    internal = _hardening.BoundEvidenceDecision(
        True,
        (),
        evidence.evidence_digest,
        evidence.candidate_id,
        evidence.candidate_digest,
        evidence.sandbox_receipt_digest,
        evidence.binding_receipt_digest,
    )
    return _BASE_REQUEST_REVIEW(
        candidate,
        internal,
        requested_role,
        now_ns=now,
    )


def _binding_identity_payload(
    decision_id: str,
    evidence: SealedCandidateEvidence,
) -> Mapping[str, object]:
    return {
        "decisionId": decision_id,
        "candidateId": evidence.candidate_id,
        "candidateDigest": evidence.candidate_digest,
        "sandboxReceiptDigest": evidence.sandbox_receipt_digest,
        "bindingReceiptDigest": evidence.binding_receipt_digest,
        "boundEvidenceDigest": evidence.base_evidence_digest,
    }


def _seal_identity_payload(
    decision_id: str,
    evidence: SealedCandidateEvidence,
    seal_digest: str,
) -> Mapping[str, object]:
    return {
        "decisionId": decision_id,
        "sealDigest": seal_digest,
        "sealedEvidenceDigest": evidence.evidence_digest,
        "issuer": evidence.issuer,
        "signingIdentity": evidence.signing_identity,
        "observedUnixNs": evidence.observed_unix_ns,
        "expiresUnixNs": evidence.expires_unix_ns,
        "signatureDigest": hashlib.sha256(evidence.signature.encode("utf-8")).hexdigest(),
    }


def record_integration_decision(
    store: _control.EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision | SealedCandidateEvidence,
    *,
    trust_store: HmacTrustStore | None = None,
    now_ns: int | None = None,
) -> None:
    now = store._now(now_ns)
    if getattr(evidence, "eligible_for_independent_review", False) is not True:
        _BASE_INELIGIBLE_RECORD(store, decision_id, evidence, now_ns=now)
        return
    if not isinstance(evidence, SealedCandidateEvidence) or trust_store is None:
        raise _control.EngineeringError("sealed_evidence_required")
    verify_sealed_candidate_evidence(evidence, trust_store, now_ns=now)
    _control.checked_id(decision_id, "decision_id")
    seal_digest = _control.semantic_digest(asdict(evidence))
    binding_semantic_digest = _control.semantic_digest(
        _binding_identity_payload(decision_id, evidence)
    )
    seal_payload = _seal_identity_payload(decision_id, evidence, seal_digest)
    seal_semantic_digest = _control.semantic_digest(seal_payload)

    def operation() -> None:
        binding = store.connection.execute(
            "SELECT candidate_id,candidate_digest,sandbox_receipt_digest,"
            "binding_receipt_digest,bound_evidence_digest,semantic_digest "
            "FROM integration_decision_bindings WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        seal = store.connection.execute(
            "SELECT seal_digest,sealed_evidence_digest,issuer,signing_identity,"
            "observed_unix_ns,expires_unix_ns,signature_digest,semantic_digest "
            "FROM integration_decision_seals WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        replay = store.connection.execute(
            "SELECT decision_id FROM integration_decision_seals WHERE seal_digest=?",
            (seal_digest,),
        ).fetchone()
        if replay is not None and str(replay[0]) != decision_id:
            raise _control.EngineeringError("sealed_evidence_replay")
        expected_binding = (
            evidence.candidate_id,
            evidence.candidate_digest,
            evidence.sandbox_receipt_digest,
            evidence.binding_receipt_digest,
            evidence.base_evidence_digest,
            binding_semantic_digest,
        )
        expected_seal = (
            seal_digest,
            evidence.evidence_digest,
            evidence.issuer,
            evidence.signing_identity,
            evidence.observed_unix_ns,
            evidence.expires_unix_ns,
            seal_payload["signatureDigest"],
            seal_semantic_digest,
        )
        if binding is not None or seal is not None:
            if binding is None or seal is None:
                raise _control.EngineeringError("decision_seal_partial_state")
            actual_binding = tuple(str(binding[index]) for index in range(6))
            actual_seal = (
                str(seal[0]),
                str(seal[1]),
                str(seal[2]),
                str(seal[3]),
                int(seal[4]),
                int(seal[5]),
                str(seal[6]),
                str(seal[7]),
            )
            if actual_binding != expected_binding or actual_seal != expected_seal:
                raise _control.EngineeringError("decision_seal_conflict")
            return
        store.connection.execute(
            "INSERT INTO integration_decision_bindings("
            "decision_id,candidate_id,candidate_digest,sandbox_receipt_digest,"
            "binding_receipt_digest,bound_evidence_digest,recorded_unix_ns,"
            "semantic_digest) VALUES(?,?,?,?,?,?,?,?)",
            (
                decision_id,
                evidence.candidate_id,
                evidence.candidate_digest,
                evidence.sandbox_receipt_digest,
                evidence.binding_receipt_digest,
                evidence.base_evidence_digest,
                now,
                binding_semantic_digest,
            ),
        )
        store.connection.execute(
            "INSERT INTO integration_decision_seals("
            "decision_id,seal_digest,sealed_evidence_digest,issuer,signing_identity,"
            "observed_unix_ns,expires_unix_ns,signature_digest,recorded_unix_ns,"
            "semantic_digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id,
                seal_digest,
                evidence.evidence_digest,
                evidence.issuer,
                evidence.signing_identity,
                evidence.observed_unix_ns,
                evidence.expires_unix_ns,
                seal_payload["signatureDigest"],
                now,
                seal_semantic_digest,
            ),
        )
        _BASE_RECORD_DECISION(
            store,
            decision_id,
            evidence.evidence_digest,
            True,
            evidence.reasons,
            now_ns=now,
        )

    _hardening._run_immediate(store, operation)


def integration_decision_seal(
    store: _control.EngineeringStore,
    decision_id: str,
) -> Mapping[str, object]:
    _control.checked_id(decision_id, "decision_id")
    row = store.connection.execute(
        "SELECT * FROM integration_decision_seals WHERE decision_id=?",
        (decision_id,),
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_integration_decision_seal")
    return {
        "decisionId": str(row["decision_id"]),
        "sealDigest": str(row["seal_digest"]),
        "sealedEvidenceDigest": str(row["sealed_evidence_digest"]),
        "issuer": str(row["issuer"]),
        "signingIdentity": str(row["signing_identity"]),
        "observedUnixNs": int(row["observed_unix_ns"]),
        "expiresUnixNs": int(row["expires_unix_ns"]),
        "signatureDigest": str(row["signature_digest"]),
        "recordedUnixNs": int(row["recorded_unix_ns"]),
        "semanticDigest": str(row["semantic_digest"]),
    }


def install_seal() -> None:
    if getattr(_control.EngineeringStore, "_lane_g_seal_installed", False):
        return
    _control.EngineeringStore.__init__ = _sealed_store_init  # type: ignore[method-assign]
    _control.EngineeringStore.integration_decision_seal = integration_decision_seal  # type: ignore[attr-defined]
    _facade.request_independent_review = request_independent_review
    _facade.record_integration_decision = record_integration_decision
    _control.EngineeringStore._lane_g_seal_installed = True  # type: ignore[attr-defined]
