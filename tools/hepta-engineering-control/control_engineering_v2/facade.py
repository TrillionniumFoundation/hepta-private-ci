"""Stable owner-clean operation facade for Lane G."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import time

from .assimilation import (
    AssimilationProposal,
    ExternalManifestCandidate,
    OwnerConsentReceipt,
    SandboxParityReceipt,
    TypedOperation,
    build_manifest_candidate,
    propose_dormant_assimilation,
    synthesize_read_only_contracts,
)
from .candidate import (
    Candidate,
    CandidateEnvelope,
    Mutation,
    SandboxReceipt,
    generate_candidates,
    sandbox_candidate,
)
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    ScheduleReceipt,
    WorkEnvelope,
    WorkPackage,
    semantic_digest,
)
from .evidence import (
    CanonicalSourceReceipt,
    EvidenceDecision,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    HmacTrustStore,
    verify_integration_evidence as _verify_integration_evidence,
)


@dataclass(frozen=True)
class ReviewRequest:
    request_id: str
    candidate_id: str
    evidence_digest: str
    requested_role: str
    created_unix_ns: int
    status: str = "review_requested"
    independent_acceptance: bool = False
    selection_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def issue_work_envelope(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    *,
    now_ns: int | None = None,
) -> WorkEnvelope:
    return store.issue_work_envelope(envelope, now_ns=now_ns)


def schedule_ready_packages(
    store: EngineeringStore,
    envelope_id: str,
    packages: Iterable[WorkPackage],
    completed: Iterable[str],
    *,
    generation_id: str,
    now_ns: int | None = None,
) -> ScheduleReceipt:
    return store.schedule_ready_packages(
        envelope_id,
        packages,
        completed,
        generation_id=generation_id,
        now_ns=now_ns,
    )


def generate_candidate(
    envelope: CandidateEnvelope,
    mutations: Iterable[Mutation],
) -> tuple[Candidate, ...]:
    return generate_candidates(envelope, mutations)


def execute_candidate_sandbox(
    repository: str | Path,
    envelope: CandidateEnvelope,
    candidate: Candidate,
    checks: Iterable[Sequence[str]],
) -> tuple[Candidate, SandboxReceipt]:
    return sandbox_candidate(repository, envelope, candidate, checks)


def verify_integration_evidence(
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    independence: EvaluatorIndependenceReceipt,
    trust_store: HmacTrustStore,
    *,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> EvidenceDecision:
    return _verify_integration_evidence(
        root,
        expected_repository,
        source,
        source_execution,
        merge_execution,
        independence,
        trust_store,
        expected_document_set_digest=expected_document_set_digest,
        now_ns=now_ns,
    )


def request_independent_review(
    candidate: Candidate,
    evidence: EvidenceDecision,
    requested_role: str,
    *,
    now_ns: int | None = None,
) -> ReviewRequest:
    if candidate.state != "sandbox_tested" or not candidate.sandbox_receipt_digest:
        raise EngineeringError("candidate_not_sandbox_tested")
    if evidence.eligible_for_independent_review is not True or evidence.reasons:
        raise EngineeringError("evidence_not_eligible")
    if requested_role not in {
        "independent_evaluator",
        "architecture_reviewer",
        "security_reviewer",
    }:
        raise EngineeringError("invalid_review_role")
    now = time.time_ns() if now_ns is None else now_ns
    body = {
        "candidateId": candidate.candidate_id,
        "candidateDigest": candidate.semantic_digest,
        "sandboxReceiptDigest": candidate.sandbox_receipt_digest,
        "evidenceDigest": evidence.evidence_digest,
        "requestedRole": requested_role,
        "createdUnixNs": now,
    }
    return ReviewRequest(
        semantic_digest(body)[:32],
        candidate.candidate_id,
        evidence.evidence_digest,
        requested_role,
        now,
    )


def record_integration_decision(
    store: EngineeringStore,
    decision_id: str,
    evidence: EvidenceDecision,
    *,
    now_ns: int | None = None,
) -> None:
    store.record_integration_decision(
        decision_id,
        evidence.evidence_digest,
        evidence.eligible_for_independent_review,
        evidence.reasons,
        now_ns=now_ns,
    )


def publish_audit_projection(
    store: EngineeringStore,
    *,
    after_sequence: int = 0,
    limit: int = 512,
) -> tuple[dict[str, object], ...]:
    return store.audit_projection(after_sequence=after_sequence, limit=limit)


def prepare_assimilation_candidate(
    consent: OwnerConsentReceipt,
    observations: dict[str, str],
    omissions: Iterable[str],
    sandbox_factory: Callable[
        [ExternalManifestCandidate, tuple[TypedOperation, ...]],
        SandboxParityReceipt,
    ],
    *,
    now_ns: int | None = None,
) -> AssimilationProposal:
    """Create a dormant proposal using a separately issued parity receipt."""
    manifest = build_manifest_candidate(
        consent,
        observations,
        omissions,
        now_ns=now_ns,
    )
    operations = synthesize_read_only_contracts(
        consent,
        manifest,
        now_ns=now_ns,
    )
    sandbox = sandbox_factory(manifest, operations)
    if not isinstance(sandbox, SandboxParityReceipt):
        raise EngineeringError("invalid_sandbox_receipt")
    return propose_dormant_assimilation(
        consent,
        manifest,
        operations,
        sandbox,
        now_ns=now_ns,
    )
