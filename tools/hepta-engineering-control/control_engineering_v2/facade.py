"""Stable owner-clean operation facade for Lane G."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .candidate import (
    Candidate,
    CandidateEnvelope,
    Mutation,
    MutationSet,
    SandboxReceipt,
    generate_candidates,
)
from .sandbox_control import SandboxCoordinator
from .control_plane import (
    EngineeringStore,
    ScheduleReceipt,
    WorkEnvelope,
    WorkPackage,
)
from .evidence import (
    CanonicalSourceReceipt,
    EvidenceDecision,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    SignatureTrustStore,
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
    compatibility_only: bool = False,
    now_ns: int | None = None,
) -> WorkEnvelope:
    """Historical local-fixture wrapper; new callers use orchestration admission."""
    if compatibility_only is not True:
        from .control_plane import EngineeringError

        raise EngineeringError("authenticated_orchestration_required")
    return store.issue_work_envelope(envelope, now_ns=now_ns)


def schedule_ready_packages(
    store: EngineeringStore,
    envelope_id: str,
    packages: Iterable[WorkPackage],
    completed: Iterable[str],
    *,
    generation_id: str,
    compatibility_only: bool = False,
    now_ns: int | None = None,
) -> ScheduleReceipt:
    """Historical local-fixture scheduler; product callers use plan_engineering_work."""
    if compatibility_only is not True:
        from .control_plane import EngineeringError

        raise EngineeringError("authenticated_orchestration_required")
    return store.schedule_ready_packages(
        envelope_id,
        packages,
        completed,
        generation_id=generation_id,
        now_ns=now_ns,
    )


def generate_candidate(
    envelope: CandidateEnvelope,
    mutations: Iterable[Mutation | MutationSet],
) -> tuple[Candidate, ...]:
    return generate_candidates(envelope, mutations)


def execute_candidate_sandbox(
    repository: str | Path,
    envelope: CandidateEnvelope,
    candidate: Candidate,
    checks: Iterable[Sequence[str]],
) -> tuple[Candidate, SandboxReceipt]:
    """Execute through the bounded host admission/retry owner."""
    result = SandboxCoordinator().execute(
        str(repository),
        envelope,
        candidate,
        checks,
    )
    return result.candidate, result.receipt


def verify_integration_evidence(
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    source_execution: ExecutionReceipt,
    merge_execution: ExecutionReceipt,
    independence: EvaluatorIndependenceReceipt,
    trust_store: SignatureTrustStore,
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
    candidate, evidence, requested_role, *, trust_store, now_ns=None
):
    """Route all public review requests through fresh, authenticated evidence."""
    from .seal import request_independent_review as sealed_review

    return sealed_review(
        candidate, evidence, requested_role, trust_store=trust_store, now_ns=now_ns
    )


def record_integration_decision(
    store, decision_id, evidence, *, trust_store=None, now_ns=None
):
    from .seal import record_integration_decision as sealed_record

    return sealed_record(
        store, decision_id, evidence, trust_store=trust_store, now_ns=now_ns
    )


def publish_audit_projection(
    store: EngineeringStore,
    *,
    after_sequence: int = 0,
    limit: int = 512,
) -> tuple[dict[str, object], ...]:
    return store.audit_projection(after_sequence=after_sequence, limit=limit)


def prepare_assimilation_candidate(
    consent,
    observations,
    omissions,
    sandbox_factory,
    *,
    trust_store,
    consent_attestation,
    now_ns=None,
):
    from .closure import prepare_assimilation_candidate as authenticated_prepare

    return authenticated_prepare(
        consent,
        observations,
        omissions,
        sandbox_factory,
        trust_store=trust_store,
        consent_attestation=consent_attestation,
        now_ns=now_ns,
    )
