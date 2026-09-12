"""Candidate evidence freshness and immutable decision-binding storage.

These functions add no module initialization hooks or schema side effects.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import time
from typing import Any

from . import assimilation as _assimilation
from . import control_plane as _control
from . import hardening as _hardening
from .candidate import Candidate, SandboxReceipt
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_BASE_BIND_CANDIDATE_EVIDENCE = _hardening.bind_candidate_evidence
_BASE_PREPARE_ASSIMILATION = _hardening.hardened_prepare_assimilation_candidate
_BASE_RECORD_DECISION = _hardening._ORIGINAL_RECORD_DECISION


def bind_candidate_evidence(
    candidate: Candidate,
    sandbox: SandboxReceipt,
    evidence: EvidenceDecision,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    binding: _hardening.CandidateEvidenceBindingReceipt,
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
) -> _hardening.BoundEvidenceDecision:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    if (
        source_execution.tree != sandbox.source_tree_before
        or source_execution.tree != sandbox.source_tree_after
    ):
        raise _control.EngineeringError("source_execution_tree_mismatch")
    lower_bound = max(
        source_execution.observed_unix_ns, merge_execution.observed_unix_ns
    )
    upper_bound = min(source_execution.expires_unix_ns, merge_execution.expires_unix_ns)
    if binding.observed_unix_ns < lower_bound or binding.expires_unix_ns > upper_bound:
        raise _control.EngineeringError("candidate_binding_window_escape")
    return _BASE_BIND_CANDIDATE_EVIDENCE(
        candidate,
        sandbox,
        evidence,
        source_execution,
        merge_execution,
        binding,
        trust_store,
        now_ns=now,
    )


def prepare_assimilation_candidate(
    consent: _assimilation.OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    sandbox_factory: Any,
    *,
    trust_store: HmacTrustStore,
    consent_attestation: _hardening.OwnerConsentAttestation,
    now_ns: int | None = None,
) -> _assimilation.AssimilationProposal:
    if (
        consent_attestation.observed_unix_ns < consent.observed_unix_ns
        or consent_attestation.expires_unix_ns > consent.expires_unix_ns
    ):
        raise _control.EngineeringError("consent_attestation_window_escape")
    return _BASE_PREPARE_ASSIMILATION(
        consent,
        observations,
        omissions,
        sandbox_factory,
        trust_store=trust_store,
        consent_attestation=consent_attestation,
        now_ns=now_ns,
    )


def record_integration_decision(
    store: _control.EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision | _hardening.BoundEvidenceDecision,
    *,
    now_ns: int | None = None,
) -> None:
    now = store._now(now_ns)
    if evidence.eligible_for_independent_review is not True:
        _hardening._run_immediate(
            store,
            lambda: _BASE_RECORD_DECISION(
                store,
                decision_id,
                evidence.evidence_digest,
                False,
                evidence.reasons,
                now_ns=now,
            ),
        )
        return
    if not isinstance(evidence, _hardening.BoundEvidenceDecision):
        raise _control.EngineeringError("candidate_binding_required")
    if evidence.candidate_bound is not True or evidence.reasons:
        raise _control.EngineeringError("candidate_binding_required")

    binding_payload = {
        "decisionId": decision_id,
        "candidateId": evidence.candidate_id,
        "candidateDigest": evidence.candidate_digest,
        "sandboxReceiptDigest": evidence.sandbox_receipt_digest,
        "bindingReceiptDigest": evidence.binding_receipt_digest,
        "boundEvidenceDigest": evidence.evidence_digest,
        "recordedUnixNs": now,
    }
    binding_semantic_digest = _control.semantic_digest(binding_payload)

    def operation() -> None:
        existing = store.connection.execute(
            "SELECT candidate_id,candidate_digest,sandbox_receipt_digest,"
            "binding_receipt_digest,bound_evidence_digest,semantic_digest "
            "FROM integration_decision_bindings WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        expected = (
            evidence.candidate_id,
            evidence.candidate_digest,
            evidence.sandbox_receipt_digest,
            evidence.binding_receipt_digest,
            evidence.evidence_digest,
            binding_semantic_digest,
        )
        if existing is None:
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
                    evidence.evidence_digest,
                    now,
                    binding_semantic_digest,
                ),
            )
        else:
            actual = tuple(str(existing[index]) for index in range(6))
            if actual != expected:
                raise _control.EngineeringError("decision_binding_conflict")
        _BASE_RECORD_DECISION(
            store,
            decision_id,
            evidence.evidence_digest,
            True,
            evidence.reasons,
            now_ns=now,
        )

    _hardening._run_immediate(store, operation)


def integration_decision_binding(
    store: _control.EngineeringStore,
    decision_id: str,
) -> Mapping[str, object]:
    _control.checked_id(decision_id, "decision_id")
    row = store.connection.execute(
        "SELECT * FROM integration_decision_bindings WHERE decision_id=?",
        (decision_id,),
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_integration_decision_binding")
    return {
        "decisionId": str(row["decision_id"]),
        "candidateId": str(row["candidate_id"]),
        "candidateDigest": str(row["candidate_digest"]),
        "sandboxReceiptDigest": str(row["sandbox_receipt_digest"]),
        "bindingReceiptDigest": str(row["binding_receipt_digest"]),
        "boundEvidenceDigest": str(row["bound_evidence_digest"]),
        "recordedUnixNs": int(row["recorded_unix_ns"]),
        "semanticDigest": str(row["semantic_digest"]),
    }
