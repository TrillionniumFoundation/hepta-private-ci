"""Exact-main and externally governed release qualification.

This gate closes the distinction between pull-request evidence and the final
protected-branch commit. All receipts are observations; even a fully qualified
decision grants no merge, deployment, runtime, promotion, or release authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .clock_policy import ClockSkewPolicy, validate_receipt_window
from .control_plane import EngineeringError, checked_id, checked_sha256, semantic_digest
from .evidence import SignatureTrustStore

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def _sha1(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise EngineeringError("invalid_" + label)
    return value


def _nonzero_digest(value: str, label: str) -> str:
    checked_sha256(value, label)
    if value == "0" * 64:
        raise EngineeringError(label + "_empty")
    return value


@dataclass(frozen=True)
class PostMergeMainReceipt:
    repository: str
    main_commit: str
    main_tree: str
    protected_branch: str
    workflow_run_id: int
    product_receipt_digest: str
    strong_sandbox_receipt_digest: str
    host_profile_digest: str
    quality_gate_receipt_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class IndependentReviewAcceptanceReceipt:
    repository: str
    source_commit: str
    source_tree: str
    generator_identity: str
    reviewer_identity: str
    review_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    accepted: bool
    signature: str = ""


@dataclass(frozen=True)
class DeploymentObservationReceipt:
    repository: str
    source_commit: str
    source_tree: str
    target_digest: str
    provider_configuration_digest: str
    external_controls_digest: str
    deployment_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    healthy: bool
    signature: str = ""


@dataclass(frozen=True)
class RollbackRehearsalReceipt:
    repository: str
    source_commit: str
    source_tree: str
    target_digest: str
    predecessor_digest: str
    backup_digest: str
    restored_snapshot_digest: str
    recovery_seconds: int
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    passed: bool
    signature: str = ""


@dataclass(frozen=True)
class OperatorAcceptanceReceipt:
    repository: str
    source_commit: str
    source_tree: str
    target_digest: str
    deployment_receipt_digest: str
    rollback_receipt_digest: str
    operator_identity: str
    acceptance_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    accepted: bool
    signature: str = ""


@dataclass(frozen=True)
class VerifiedReleaseReceipts:
    post_merge_main_digest: str
    independent_review_digest: str
    deployment_digest: str
    rollback_digest: str
    operator_acceptance_digest: str


@dataclass(frozen=True)
class ReleaseQualificationFacts:
    repository: str
    source_commit: str
    source_tree: str
    pull_request_source_product_digest: str
    pull_request_merge_product_digest: str
    pull_request_pair_digest: str
    post_merge_main_digest: str
    quality_gate_digest: str
    distributed_fence_digest: str
    external_audit_anchor_digest: str
    key_custody_digest: str
    independent_completion_digest: str
    terminal_observation_digest: str
    independent_review_digest: str
    deployment_digest: str
    rollback_digest: str
    operator_acceptance_digest: str
    authority_delta: bool = False


@dataclass(frozen=True)
class ReleaseQualificationDecision:
    repository_implementation_qualified: bool
    deployment_qualified: bool
    release_evidence_complete: bool
    implementation_blockers: tuple[str, ...]
    deployment_blockers: tuple[str, ...]
    evidence_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    deployment_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _verify_signed(
    receipt: object,
    trust_store: SignatureTrustStore,
    *,
    issuer: str,
    clock_policy: ClockSkewPolicy,
    now_ns: int,
) -> str:
    observed = getattr(receipt, "observed_unix_ns", None)
    expires = getattr(receipt, "expires_unix_ns", None)
    actual_issuer = getattr(receipt, "issuer", None)
    signing_identity = getattr(receipt, "signing_identity", None)
    signature = getattr(receipt, "signature", None)
    if actual_issuer != issuer:
        raise EngineeringError("release_receipt_issuer_role")
    checked_id(signing_identity, "release_signing_identity")
    validate_receipt_window(
        observed,
        expires,
        now_ns=now_ns,
        policy=clock_policy,
    )
    if not trust_store.verify(receipt, actual_issuer, signing_identity, signature):
        raise EngineeringError("release_receipt_signature")
    return semantic_digest(asdict(receipt))


def verify_release_receipts(
    *,
    post_merge: PostMergeMainReceipt,
    review: IndependentReviewAcceptanceReceipt,
    deployment: DeploymentObservationReceipt,
    rollback: RollbackRehearsalReceipt,
    operator: OperatorAcceptanceReceipt,
    trust_store: SignatureTrustStore,
    expected_repository: str,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_quality_gate_digest: str,
    expected_provider_configuration_digest: str,
    clock_policy: ClockSkewPolicy = ClockSkewPolicy(),
    now_ns: int,
) -> VerifiedReleaseReceipts:
    checked_id(expected_repository, "expected_release_repository")
    _sha1(expected_source_commit, "expected_release_source_commit")
    _sha1(expected_source_tree, "expected_release_source_tree")
    _nonzero_digest(expected_quality_gate_digest, "expected_quality_gate_digest")
    _nonzero_digest(
        expected_provider_configuration_digest,
        "expected_provider_configuration_digest",
    )
    typed = (
        (post_merge, PostMergeMainReceipt),
        (review, IndependentReviewAcceptanceReceipt),
        (deployment, DeploymentObservationReceipt),
        (rollback, RollbackRehearsalReceipt),
        (operator, OperatorAcceptanceReceipt),
    )
    if any(not isinstance(value, cls) for value, cls in typed):
        raise EngineeringError("release_receipt_type")
    if (
        post_merge.repository != expected_repository
        or post_merge.main_commit != expected_source_commit
        or post_merge.main_tree != expected_source_tree
        or post_merge.protected_branch != "main"
    ):
        raise EngineeringError("post_merge_main_binding")
    if type(post_merge.workflow_run_id) is not int or post_merge.workflow_run_id < 1:
        raise EngineeringError("post_merge_workflow_run")
    for value, label in (
        (post_merge.product_receipt_digest, "post_merge_product_receipt_digest"),
        (post_merge.strong_sandbox_receipt_digest, "post_merge_sandbox_receipt_digest"),
        (post_merge.host_profile_digest, "post_merge_host_profile_digest"),
        (post_merge.quality_gate_receipt_digest, "post_merge_quality_gate_digest"),
    ):
        _nonzero_digest(value, label)
    if post_merge.quality_gate_receipt_digest != expected_quality_gate_digest:
        raise EngineeringError("post_merge_quality_gate_mismatch")

    for value in (review, deployment, rollback, operator):
        if (
            value.repository != expected_repository
            or value.source_commit != expected_source_commit
            or value.source_tree != expected_source_tree
        ):
            raise EngineeringError("release_receipt_source_binding")
    checked_id(review.generator_identity, "generator_identity")
    checked_id(review.reviewer_identity, "reviewer_identity")
    if review.generator_identity == review.reviewer_identity:
        raise EngineeringError("reviewer_identity_collision")
    if review.accepted is not True:
        raise EngineeringError("independent_review_not_accepted")
    _nonzero_digest(review.review_digest, "independent_review_digest")

    for value, label in (
        (deployment.target_digest, "deployment_target_digest"),
        (deployment.provider_configuration_digest, "provider_configuration_digest"),
        (deployment.external_controls_digest, "deployment_external_controls_digest"),
        (deployment.deployment_digest, "deployment_digest"),
    ):
        _nonzero_digest(value, label)
    if deployment.provider_configuration_digest != expected_provider_configuration_digest:
        raise EngineeringError("provider_configuration_mismatch")
    if deployment.healthy is not True:
        raise EngineeringError("deployment_not_healthy")

    for value, label in (
        (rollback.target_digest, "rollback_target_digest"),
        (rollback.predecessor_digest, "rollback_predecessor_digest"),
        (rollback.backup_digest, "rollback_backup_digest"),
        (rollback.restored_snapshot_digest, "rollback_snapshot_digest"),
    ):
        _nonzero_digest(value, label)
    if rollback.target_digest != deployment.target_digest or rollback.passed is not True:
        raise EngineeringError("rollback_rehearsal_not_passed")
    if type(rollback.recovery_seconds) is not int or rollback.recovery_seconds < 0:
        raise EngineeringError("rollback_recovery_time")

    for value, label in (
        (operator.target_digest, "operator_target_digest"),
        (operator.deployment_receipt_digest, "operator_deployment_digest"),
        (operator.rollback_receipt_digest, "operator_rollback_digest"),
        (operator.acceptance_digest, "operator_acceptance_digest"),
    ):
        _nonzero_digest(value, label)
    checked_id(operator.operator_identity, "operator_identity")
    if operator.target_digest != deployment.target_digest or operator.accepted is not True:
        raise EngineeringError("operator_acceptance_missing")

    post_digest = _verify_signed(
        post_merge,
        trust_store,
        issuer="ci_executor",
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    review_digest = _verify_signed(
        review,
        trust_store,
        issuer="independent_evaluator",
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    deployment_digest = _verify_signed(
        deployment,
        trust_store,
        issuer="deployment_observer",
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    rollback_digest = _verify_signed(
        rollback,
        trust_store,
        issuer="rollback_observer",
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    operator_digest = _verify_signed(
        operator,
        trust_store,
        issuer="operator_acceptance_authority",
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    if operator.deployment_receipt_digest != deployment_digest:
        raise EngineeringError("operator_deployment_receipt_mismatch")
    if operator.rollback_receipt_digest != rollback_digest:
        raise EngineeringError("operator_rollback_receipt_mismatch")
    return VerifiedReleaseReceipts(
        post_digest,
        review_digest,
        deployment_digest,
        rollback_digest,
        operator_digest,
    )


def evaluate_release_qualification(
    facts: ReleaseQualificationFacts,
) -> ReleaseQualificationDecision:
    if not isinstance(facts, ReleaseQualificationFacts):
        raise EngineeringError("release_qualification_facts_required")
    checked_id(facts.repository, "release_repository")
    _sha1(facts.source_commit, "release_source_commit")
    _sha1(facts.source_tree, "release_source_tree")
    implementation: list[str] = []
    deployment: list[str] = []

    implementation_fields = (
        ("pull_request_source_product", facts.pull_request_source_product_digest),
        ("pull_request_merge_product", facts.pull_request_merge_product_digest),
        ("pull_request_pair", facts.pull_request_pair_digest),
        ("post_merge_main", facts.post_merge_main_digest),
        ("quality_gate", facts.quality_gate_digest),
    )
    deployment_fields = (
        ("distributed_fence", facts.distributed_fence_digest),
        ("external_audit_anchor", facts.external_audit_anchor_digest),
        ("key_custody", facts.key_custody_digest),
        ("independent_completion", facts.independent_completion_digest),
        ("terminal_observation", facts.terminal_observation_digest),
        ("independent_review", facts.independent_review_digest),
        ("deployment", facts.deployment_digest),
        ("rollback", facts.rollback_digest),
        ("operator_acceptance", facts.operator_acceptance_digest),
    )
    for name, value in implementation_fields:
        try:
            _nonzero_digest(value, name + "_digest")
        except EngineeringError:
            implementation.append(name + "_missing")
    deployment.extend(implementation)
    for name, value in deployment_fields:
        try:
            _nonzero_digest(value, name + "_digest")
        except EngineeringError:
            deployment.append(name + "_missing")
    if facts.authority_delta is not False:
        implementation.append("authority_delta")
        deployment.append("authority_delta")
    implementation_blockers = tuple(sorted(set(implementation)))
    deployment_blockers = tuple(sorted(set(deployment)))
    return ReleaseQualificationDecision(
        repository_implementation_qualified=not implementation_blockers,
        deployment_qualified=not deployment_blockers,
        release_evidence_complete=not deployment_blockers,
        implementation_blockers=implementation_blockers,
        deployment_blockers=deployment_blockers,
        evidence_digest=semantic_digest(asdict(facts)),
    )
