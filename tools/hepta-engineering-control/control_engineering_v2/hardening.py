"""Fail-closed repository-owned hardening for Lane G engineering control.

The V2 implementation deliberately stops before independent acceptance, merge,
activation, promotion, release, deployment, peer enrollment, credential
propagation, or runtime authority.  This module strengthens the boundaries that
must nevertheless be enforced by repository-owned source:

* every owner mutation starts with ``BEGIN IMMEDIATE``;
* assignment generations bind an immutable envelope/lease frontier;
* candidate checks are non-empty and execute in a detached local clone rather
  than a worktree sharing the source repository's Git directory;
* exact evidence must receive a separately signed candidate binding before it
  can create a review request or an eligible persisted decision; and
* external-owner consent plus sandbox parity are authenticated before a dormant
  assimilation proposal can be composed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
import functools
import json
from pathlib import Path
import re
import time
from typing import Any

from . import assimilation as _assimilation
from . import candidate as _candidate
from . import control_plane as _control
from . import facade as _facade
from .evidence import EvidenceDecision, ExecutionReceipt, HmacTrustStore

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_MAX_COMMAND_ARGUMENT_BYTES = 8_192
_MAX_COMMAND_BYTES = 65_536
_STORE_SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# Stable fail-closed error identity
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SQLite transaction and assignment-frontier hardening
# ---------------------------------------------------------------------------

_ORIGINAL_STORE_INIT = _control.EngineeringStore.__init__
_ORIGINAL_ISSUE_ENVELOPE = _control.EngineeringStore.issue_work_envelope
_ORIGINAL_ACQUIRE_LEASE = _control.EngineeringStore.acquire_path_lease
_ORIGINAL_TRANSITION_LEASE = _control.EngineeringStore.transition_path_lease
_ORIGINAL_SCHEDULE = _control.EngineeringStore.schedule_ready_packages
_ORIGINAL_RECORD_DECISION = _control.EngineeringStore.record_integration_decision


def _install_store_schema(store: _control.EngineeringStore) -> None:
    store.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS engineering_schema_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          schema_version INTEGER NOT NULL CHECK(schema_version>=1),
          updated_unix_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assignment_generation_frontiers(
          generation_id TEXT PRIMARY KEY,
          envelope_id TEXT NOT NULL,
          envelope_revision INTEGER NOT NULL CHECK(envelope_revision>=1),
          source_commit TEXT NOT NULL,
          source_tree TEXT NOT NULL,
          frontier_digest TEXT NOT NULL,
          created_unix_ns INTEGER NOT NULL,
          FOREIGN KEY(generation_id)
            REFERENCES assignment_generations(generation_id)
            DEFERRABLE INITIALLY DEFERRED,
          FOREIGN KEY(envelope_id) REFERENCES work_envelopes(envelope_id)
        );
        """
    )
    now = time.time_ns()
    row = store.connection.execute(
        "SELECT schema_version FROM engineering_schema_meta WHERE singleton=1"
    ).fetchone()
    if row is not None and int(row[0]) > _STORE_SCHEMA_VERSION:
        raise _control.EngineeringError("unsupported_future_store_schema")
    store.connection.execute(
        "INSERT INTO engineering_schema_meta(singleton,schema_version,updated_unix_ns) "
        "VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET "
        "schema_version=excluded.schema_version,updated_unix_ns=excluded.updated_unix_ns",
        (_STORE_SCHEMA_VERSION, now),
    )
    store.connection.execute(f"PRAGMA user_version={_STORE_SCHEMA_VERSION}")
    store.connection.commit()


def _hardened_store_init(self: _control.EngineeringStore, database: str | Path) -> None:
    _ORIGINAL_STORE_INIT(self, database)
    try:
        _install_store_schema(self)
    except BaseException:
        self.connection.close()
        raise


def _run_immediate(
    store: _control.EngineeringStore,
    operation: Callable[[], Any],
) -> Any:
    connection = store.connection
    if connection.in_transaction:
        raise _control.EngineeringError("nested_engineering_transaction")
    connection.execute("BEGIN IMMEDIATE")
    try:
        value = operation()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    if connection.in_transaction:
        connection.commit()
    return value


def _immediate_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def wrapped(self: _control.EngineeringStore, *args: Any, **kwargs: Any) -> Any:
        return _run_immediate(self, lambda: method(self, *args, **kwargs))

    return wrapped


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
    leases = []
    for row in rows:
        leases.append(
            {
                "leaseId": str(row["lease_id"]),
                "envelopeId": str(row["envelope_id"]),
                "holder": str(row["holder"]),
                "paths": json.loads(bytes(row["paths_json"]).decode("utf-8")),
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


def _hardened_schedule(
    self: _control.EngineeringStore,
    envelope_id: str,
    packages: Iterable[_control.WorkPackage],
    completed: Iterable[str],
    *,
    generation_id: str,
    now_ns: int | None = None,
) -> _control.ScheduleReceipt:
    _control.checked_id(generation_id, "generation_id")
    now = self._now(now_ns)

    def operation() -> _control.ScheduleReceipt:
        self._expire_leases(now)
        envelope = self._get_envelope(envelope_id, now)
        frontier = _lease_frontier(self, envelope, now)
        current = self.connection.execute(
            "SELECT frontier_digest FROM assignment_generation_frontiers "
            "WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        assignment_exists = self.connection.execute(
            "SELECT 1 FROM assignment_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if current is None and assignment_exists is not None:
            raise _control.EngineeringError("unbound_legacy_generation")
        if current is not None and str(current[0]) != frontier:
            raise _control.EngineeringError("generation_frontier_conflict")
        if current is None:
            self.connection.execute(
                "INSERT INTO assignment_generation_frontiers("
                "generation_id,envelope_id,envelope_revision,source_commit,source_tree,"
                "frontier_digest,created_unix_ns) VALUES(?,?,?,?,?,?,?)",
                (
                    generation_id,
                    envelope_id,
                    int(envelope["revision"]),
                    str(envelope["source_commit"]),
                    str(envelope["source_tree"]),
                    frontier,
                    now,
                ),
            )
        return _ORIGINAL_SCHEDULE(
            self,
            envelope_id,
            packages,
            completed,
            generation_id=generation_id,
            now_ns=now,
        )

    return _run_immediate(self, operation)


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
    for execution, kind in ((source_execution, "exact_source"), (merge_execution, "synthetic_merge")):
        if execution.class_name != kind or execution.passed is not True or execution.issuer != "ci_executor":
            raise _control.EngineeringError("execution_evidence_invalid")
        if not _valid_window(execution.observed_unix_ns, execution.expires_unix_ns, now):
            raise _control.EngineeringError("execution_evidence_stale")
        if not trust_store.verify(execution, execution.issuer, execution.signing_identity, execution.signature):
            raise _control.EngineeringError("execution_evidence_signature")
    if (len(merge_execution.ordered_parents) != 2
            or merge_execution.ordered_parents[1] != candidate.base_commit
            or merge_execution.commit in merge_execution.ordered_parents):
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
    if not isinstance(evidence, BoundEvidenceDecision) or evidence.candidate_bound is not True:
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
        if not isinstance(evidence, BoundEvidenceDecision) or evidence.candidate_bound is not True:
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
        [_assimilation.ExternalManifestCandidate, tuple[_assimilation.TypedOperation, ...]],
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


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def install_hardening() -> None:
    if getattr(_control.EngineeringStore, "_lane_g_hardening_installed", False):
        return
    _control.EngineeringStore.__init__ = _hardened_store_init  # type: ignore[method-assign]
    _control.EngineeringStore.issue_work_envelope = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_ISSUE_ENVELOPE
    )
    _control.EngineeringStore.acquire_path_lease = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_ACQUIRE_LEASE
    )
    _control.EngineeringStore.transition_path_lease = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_TRANSITION_LEASE
    )
    _control.EngineeringStore.schedule_ready_packages = _hardened_schedule  # type: ignore[method-assign]
    _control.EngineeringStore.record_integration_decision = _immediate_wrapper(  # type: ignore[method-assign]
        _ORIGINAL_RECORD_DECISION
    )
    _control.EngineeringStore.assignment_frontier = assignment_frontier  # type: ignore[attr-defined]

    _facade.execute_candidate_sandbox = hardened_execute_candidate_sandbox
    _facade.request_independent_review = hardened_request_independent_review
    _facade.record_integration_decision = hardened_record_integration_decision
    _facade.prepare_assimilation_candidate = hardened_prepare_assimilation_candidate
    _control.EngineeringStore._lane_g_hardening_installed = True  # type: ignore[attr-defined]
