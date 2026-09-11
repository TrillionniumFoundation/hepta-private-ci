"""Assignment frontiers and authenticated candidate/assimilation evidence.

Storage and schema evolution are owned directly by EngineeringStore. The sole
candidate executor is candidate.py; this module never patches either owner.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
import json
import time
from typing import Any

from . import assimilation as _assimilation
from . import candidate as _candidate
from . import control_plane as _control
from . import facade as _facade
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_ORIGINAL_RECORD_DECISION = _control.EngineeringStore.record_integration_decision


def _run_immediate(store, operation):
    with store._transaction():
        return operation()


def _decode_paths_json(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bytes, bytearray, memoryview)):
        try:
            text = bytes(value).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _control.EngineeringError("invalid_lease_paths_encoding") from None
    else:
        raise _control.EngineeringError("invalid_lease_paths_encoding")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        raise _control.EngineeringError("invalid_lease_paths_encoding") from None
    if not isinstance(decoded, list) or not all(
        isinstance(item, str) for item in decoded
    ):
        raise _control.EngineeringError("invalid_lease_paths_encoding")
    return tuple(decoded)


def _lease_frontier(
    store: _control.EngineeringStore,
    envelope: Any,
    now_ns: int,
) -> str:
    rows = store.connection.execute(
        "SELECT lease_id,envelope_id,holder,paths_json,state,authority_epoch,"
        "fencing_token,revision,issued_unix_ns,expires_unix_ns,semantic_digest "
        "FROM path_leases WHERE state='active' AND expires_unix_ns>? "
        "ORDER BY fencing_token,lease_id",
        (now_ns,),
    ).fetchall()
    leases: list[dict[str, object]] = []
    for row in rows:
        leases.append(
            {
                "leaseId": str(row["lease_id"]),
                "envelopeId": str(row["envelope_id"]),
                "holder": str(row["holder"]),
                "paths": _decode_paths_json(row["paths_json"]),
                "state": str(row["state"]),
                "authorityEpoch": int(row["authority_epoch"]),
                "fencingToken": int(row["fencing_token"]),
                "revision": int(row["revision"]),
                "issuedUnixNs": int(row["issued_unix_ns"]),
                "expiresUnixNs": int(row["expires_unix_ns"]),
                "semanticDigest": str(row["semantic_digest"]),
            }
        )
    return _control.semantic_digest(
        {
            "envelopeId": str(envelope["envelope_id"]),
            "envelopeSemanticDigest": str(envelope["semantic_digest"]),
            "envelopeRevision": int(envelope["revision"]),
            "sourceCommit": str(envelope["source_commit"]),
            "sourceTree": str(envelope["source_tree"]),
            "activeLeases": leases,
        }
    )


def bind_assignment_frontier(store, envelope, generation_id, now):
    """Bind the exact state read by the scheduler within its owner transaction."""
    frontier = _lease_frontier(store, envelope, now)
    current = store.connection.execute(
        "SELECT frontier_digest FROM assignment_generation_frontiers WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    existing = store.connection.execute(
        "SELECT 1 FROM assignment_generations WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    if current is None and existing is not None:
        raise _control.EngineeringError("unbound_legacy_generation")
    if current is not None and current[0] != frontier:
        raise _control.EngineeringError("generation_frontier_conflict")
    if current is None:
        store.connection.execute(
            "INSERT INTO assignment_generation_frontiers VALUES(?,?,?,?,?,?,?)",
            (
                generation_id,
                envelope["envelope_id"],
                envelope["revision"],
                envelope["source_commit"],
                envelope["source_tree"],
                frontier,
                now,
            ),
        )


def assignment_frontier(
    store: _control.EngineeringStore,
    generation_id: str,
) -> Mapping[str, object]:
    _control.checked_id(generation_id, "generation_id")
    row = store.connection.execute(
        "SELECT * FROM assignment_generation_frontiers WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    if row is None:
        raise _control.EngineeringError("unknown_assignment_frontier")
    return {
        "generationId": str(row["generation_id"]),
        "envelopeId": str(row["envelope_id"]),
        "envelopeRevision": int(row["envelope_revision"]),
        "sourceCommit": str(row["source_commit"]),
        "sourceTree": str(row["source_tree"]),
        "frontierDigest": str(row["frontier_digest"]),
        "createdUnixNs": int(row["created_unix_ns"]),
    }


# ---------------------------------------------------------------------------
# Candidate sandbox hardening
# ---------------------------------------------------------------------------


def hardened_sandbox_candidate(repository, envelope, candidate, checks):
    """Compatibility entrypoint for the single metadata-free sandbox owner."""
    return _candidate.sandbox_candidate(repository, envelope, candidate, checks)


def hardened_execute_candidate_sandbox(repository, envelope, candidate, checks):
    return _candidate.sandbox_candidate(repository, envelope, candidate, checks)


# ---------------------------------------------------------------------------
# Candidate-bound evidence and independent-review transition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateEvidenceBindingReceipt:
    candidate_id: str
    candidate_digest: str
    sandbox_receipt_digest: str
    base_commit: str
    evidence_digest: str
    source_execution_digest: str
    merge_execution_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class BoundEvidenceDecision:
    eligible_for_independent_review: bool
    reasons: tuple[str, ...]
    evidence_digest: str
    candidate_id: str
    candidate_digest: str
    sandbox_receipt_digest: str
    binding_receipt_digest: str
    candidate_bound: bool = True
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and type(now) is int
        and observed <= now < expires
        and expires > observed
    )


def bind_candidate_evidence(
    candidate: _candidate.Candidate,
    sandbox: _candidate.SandboxReceipt,
    evidence: EvidenceDecision,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    binding: CandidateEvidenceBindingReceipt,
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
) -> BoundEvidenceDecision:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    if evidence.eligible_for_independent_review is not True or evidence.reasons:
        raise _control.EngineeringError("evidence_not_eligible")
    for name in (
        "runtime_authority",
        "merge_authority",
        "activation_authority",
        "promotion_authority",
        "release_authority",
    ):
        if getattr(evidence, name, False) is not False:
            raise _control.EngineeringError("evidence_authority_delta")
    if candidate.state != "sandbox_tested" or not candidate.sandbox_receipt_digest:
        raise _control.EngineeringError("candidate_not_sandbox_tested")
    actual_sandbox_digest = _control.semantic_digest(asdict(sandbox))
    if (
        sandbox.candidate_id != candidate.candidate_id
        or sandbox.base_commit != candidate.base_commit
        or candidate.sandbox_receipt_digest != actual_sandbox_digest
        or sandbox.passed is not True
        or sandbox.authority_delta is not False
    ):
        raise _control.EngineeringError("sandbox_candidate_binding_mismatch")
    if (
        sandbox.filesystem_isolated is not True
        or sandbox.network_isolated is not True
        or sandbox.isolation_adapter != "bubblewrap-unshare-all-ro-workspace-v2"
        or sandbox.credential_environment_count != 0
        or not sandbox.check_results
        or any(type(code) is not int or code != 0 for _, code in sandbox.check_results)
        or sandbox.candidate_state_digest_before != sandbox.candidate_state_digest_after
        or sandbox.source_worktree_digest_before != sandbox.source_worktree_digest_after
    ):
        raise _control.EngineeringError("sandbox_isolation_evidence_required")
    for digest in (
        sandbox.check_set_digest,
        sandbox.candidate_state_digest_before,
        sandbox.source_worktree_digest_before,
    ):
        _control.checked_sha256(digest, "sandbox_evidence_digest")
        if digest == "0" * 64:
            raise _control.EngineeringError("sandbox_isolation_evidence_required")
    for execution, kind in (
        (source_execution, "exact_source"),
        (merge_execution, "synthetic_merge"),
    ):
        if (
            execution.class_name != kind
            or execution.passed is not True
            or execution.issuer != "ci_executor"
        ):
            raise _control.EngineeringError("execution_evidence_invalid")
        if not _valid_window(
            execution.observed_unix_ns, execution.expires_unix_ns, now
        ):
            raise _control.EngineeringError("execution_evidence_stale")
        if not trust_store.verify(
            execution, execution.issuer, execution.signing_identity, execution.signature
        ):
            raise _control.EngineeringError("execution_evidence_signature")
    if (
        len(merge_execution.ordered_parents) != 2
        or merge_execution.ordered_parents[1] != candidate.base_commit
        or merge_execution.commit in merge_execution.ordered_parents
    ):
        raise _control.EngineeringError("execution_merge_parent_mismatch")
    source_digest = _control.semantic_digest(asdict(source_execution))
    merge_digest = _control.semantic_digest(asdict(merge_execution))
    for value, label in (
        (candidate.semantic_digest, "candidate_digest"),
        (actual_sandbox_digest, "sandbox_receipt_digest"),
        (evidence.evidence_digest, "evidence_digest"),
        (source_digest, "source_execution_digest"),
        (merge_digest, "merge_execution_digest"),
    ):
        _control.checked_sha256(value, label)
    _control.checked_id(binding.candidate_id, "candidate_id")
    if (
        binding.candidate_id != candidate.candidate_id
        or binding.candidate_digest != candidate.semantic_digest
        or binding.sandbox_receipt_digest != actual_sandbox_digest
        or binding.base_commit != candidate.base_commit
        or binding.evidence_digest != evidence.evidence_digest
        or binding.source_execution_digest != source_digest
        or binding.merge_execution_digest != merge_digest
        or source_execution.commit != candidate.base_commit
    ):
        raise _control.EngineeringError("candidate_evidence_binding_mismatch")
    if binding.issuer != "ci_executor":
        raise _control.EngineeringError("candidate_binding_issuer_role")
    if not _valid_window(binding.observed_unix_ns, binding.expires_unix_ns, now):
        raise _control.EngineeringError("candidate_binding_stale")
    if not trust_store.verify(
        binding,
        binding.issuer,
        binding.signing_identity,
        binding.signature,
    ):
        raise _control.EngineeringError("candidate_binding_signature")
    binding_digest = _control.semantic_digest(asdict(binding))
    bound_digest = _control.semantic_digest(
        {
            "baseEvidenceDigest": evidence.evidence_digest,
            "candidateId": candidate.candidate_id,
            "candidateDigest": candidate.semantic_digest,
            "sandboxReceiptDigest": actual_sandbox_digest,
            "bindingReceiptDigest": binding_digest,
        }
    )
    return BoundEvidenceDecision(
        True,
        (),
        bound_digest,
        candidate.candidate_id,
        candidate.semantic_digest,
        actual_sandbox_digest,
        binding_digest,
    )


def hardened_request_independent_review(
    candidate: _candidate.Candidate,
    evidence: BoundEvidenceDecision,
    requested_role: str,
    *,
    now_ns: int | None = None,
) -> _facade.ReviewRequest:
    if (
        not isinstance(evidence, BoundEvidenceDecision)
        or evidence.candidate_bound is not True
    ):
        raise _control.EngineeringError("candidate_binding_required")
    if candidate.state != "sandbox_tested" or not candidate.sandbox_receipt_digest:
        raise _control.EngineeringError("candidate_not_sandbox_tested")
    if (
        evidence.eligible_for_independent_review is not True
        or evidence.reasons
        or evidence.candidate_id != candidate.candidate_id
        or evidence.candidate_digest != candidate.semantic_digest
        or evidence.sandbox_receipt_digest != candidate.sandbox_receipt_digest
    ):
        raise _control.EngineeringError("evidence_not_eligible")
    if requested_role not in {
        "independent_evaluator",
        "architecture_reviewer",
        "security_reviewer",
    }:
        raise _control.EngineeringError("invalid_review_role")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    body = {
        "candidateId": candidate.candidate_id,
        "candidateDigest": candidate.semantic_digest,
        "sandboxReceiptDigest": candidate.sandbox_receipt_digest,
        "boundEvidenceDigest": evidence.evidence_digest,
        "bindingReceiptDigest": evidence.binding_receipt_digest,
        "requestedRole": requested_role,
        "createdUnixNs": now,
    }
    return _facade.ReviewRequest(
        _control.semantic_digest(body)[:32],
        candidate.candidate_id,
        evidence.evidence_digest,
        requested_role,
        now,
    )


def hardened_record_integration_decision(
    store: _control.EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision | BoundEvidenceDecision,
    *,
    now_ns: int | None = None,
) -> None:
    if evidence.eligible_for_independent_review is True:
        if (
            not isinstance(evidence, BoundEvidenceDecision)
            or evidence.candidate_bound is not True
        ):
            raise _control.EngineeringError("candidate_binding_required")
    store.record_integration_decision(
        decision_id,
        evidence.evidence_digest,
        evidence.eligible_for_independent_review,
        evidence.reasons,
        now_ns=now_ns,
    )


# ---------------------------------------------------------------------------
# Authenticated dormant assimilation composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnerConsentAttestation:
    owner_principal: str
    target_identity_digest: str
    consent_payload_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class SandboxParityAttestation:
    sandbox_receipt_digest: str
    manifest_digest: str
    operations_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class AttestedSandboxParity:
    receipt: _assimilation.SandboxParityReceipt
    attestation: SandboxParityAttestation


def consent_payload_digest(receipt: _assimilation.OwnerConsentReceipt) -> str:
    value = _assimilation.validate_consent(receipt)
    return _control.semantic_digest(
        {
            "ownerPrincipal": value.owner_principal,
            "targetIdentityDigest": value.target_identity_digest,
            "allowedOperations": value.allowed_operations,
            "allowedRoots": value.allowed_roots,
            "observedUnixNs": value.observed_unix_ns,
            "expiresUnixNs": value.expires_unix_ns,
        }
    )


def hardened_prepare_assimilation_candidate(
    consent: _assimilation.OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    sandbox_factory: Callable[
        [
            _assimilation.ExternalManifestCandidate,
            tuple[_assimilation.TypedOperation, ...],
        ],
        AttestedSandboxParity,
    ],
    *,
    trust_store: HmacTrustStore,
    consent_attestation: OwnerConsentAttestation,
    now_ns: int | None = None,
) -> _assimilation.AssimilationProposal:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    value = _assimilation.validate_consent(consent, now_ns=now)
    payload_digest = _control.semantic_digest(
        {
            "ownerPrincipal": value.owner_principal,
            "targetIdentityDigest": value.target_identity_digest,
            "allowedOperations": value.allowed_operations,
            "allowedRoots": value.allowed_roots,
            "observedUnixNs": value.observed_unix_ns,
            "expiresUnixNs": value.expires_unix_ns,
        }
    )
    if value.receipt_digest != payload_digest:
        raise _control.EngineeringError("consent_payload_digest_mismatch")
    if (
        consent_attestation.owner_principal != value.owner_principal
        or consent_attestation.target_identity_digest != value.target_identity_digest
        or consent_attestation.consent_payload_digest != payload_digest
        or consent_attestation.issuer != value.owner_principal
    ):
        raise _control.EngineeringError("consent_attestation_mismatch")
    if not _valid_window(
        consent_attestation.observed_unix_ns,
        consent_attestation.expires_unix_ns,
        now,
    ):
        raise _control.EngineeringError("consent_attestation_stale")
    if not trust_store.verify(
        consent_attestation,
        consent_attestation.issuer,
        consent_attestation.signing_identity,
        consent_attestation.signature,
    ):
        raise _control.EngineeringError("consent_attestation_signature")

    manifest = _assimilation.build_manifest_candidate(
        value,
        observations,
        omissions,
        now_ns=now,
    )
    operations = _assimilation.synthesize_read_only_contracts(
        value,
        manifest,
        now_ns=now,
    )
    attested = sandbox_factory(manifest, operations)
    if not isinstance(attested, AttestedSandboxParity):
        raise _control.EngineeringError("sandbox_attestation_missing")
    sandbox = attested.receipt
    parity = attested.attestation
    sandbox_digest = _control.semantic_digest(asdict(sandbox))
    manifest_digest = _control.semantic_digest(asdict(manifest))
    operations_digest = _control.semantic_digest([asdict(item) for item in operations])
    if (
        parity.sandbox_receipt_digest != sandbox_digest
        or parity.manifest_digest != manifest_digest
        or parity.operations_digest != operations_digest
        or parity.issuer != sandbox.evaluator_principal
    ):
        raise _control.EngineeringError("sandbox_attestation_mismatch")
    if not _valid_window(parity.observed_unix_ns, parity.expires_unix_ns, now):
        raise _control.EngineeringError("sandbox_attestation_stale")
    if not trust_store.verify(
        parity,
        parity.issuer,
        parity.signing_identity,
        parity.signature,
    ):
        raise _control.EngineeringError("sandbox_attestation_signature")
    return _assimilation.propose_dormant_assimilation(
        value,
        manifest,
        operations,
        sandbox,
        now_ns=now,
    )
