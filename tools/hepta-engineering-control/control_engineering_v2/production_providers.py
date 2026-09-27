"""Fail-closed external production-provider contracts for control.engineering.

The repository defines and verifies the boundary but cannot manufacture an
independent lease service, immutable log, HSM/KMS, deployment host, observer,
reviewer, or operator. Production callers inject real providers whose descriptors
and signed receipts pass these checks. Fixture providers are permanently ineligible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Protocol, runtime_checkable

from .clock_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_POLICY,
    checked_now,
    validate_signed_window,
)
from .control_plane import EngineeringError, checked_id, checked_sha256, semantic_digest
from .evidence import SignatureTrustStore

_GIT_OID = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_SCHEMES = frozenset({"https", "pkcs11", "kms", "opaque"})
_REQUIRED_PROVIDER_ROLES = (
    "distributed_fence",
    "immutable_audit_log",
    "key_custody",
    "completion_observer",
    "terminal_integration_observer",
    "semantic_review",
    "deployment_controller",
    "operator_acceptance",
)


@dataclass(frozen=True)
class ExternalProviderDescriptor:
    provider_id: str
    role: str
    endpoint_scheme: str
    external_to_repository: bool
    fixture: bool
    trust_domain: str
    signing_identity: str
    configuration_digest: str


@dataclass(frozen=True)
class ProductionProviderSet:
    distributed_fence: ExternalProviderDescriptor
    immutable_audit_log: ExternalProviderDescriptor
    key_custody: ExternalProviderDescriptor
    completion_observer: ExternalProviderDescriptor
    terminal_integration_observer: ExternalProviderDescriptor
    semantic_review: ExternalProviderDescriptor
    deployment_controller: ExternalProviderDescriptor
    operator_acceptance: ExternalProviderDescriptor


@dataclass(frozen=True)
class ProductionEvidenceBundle:
    source_commit: str
    source_tree: str
    target_digest: str
    provider_set_digest: str
    product_receipt_pair_digest: str
    post_merge_main_receipt_digest: str
    strong_sandbox_receipt_digest: str
    distributed_fence_receipt_digest: str
    immutable_audit_anchor_digest: str
    source_key_custody_digest: str
    ci_key_custody_digest: str
    review_key_custody_digest: str
    integration_key_custody_digest: str
    completion_observation_digest: str
    terminal_observation_digest: str
    independent_review_digest: str
    backup_digest: str
    recovery_report_digest: str


@dataclass(frozen=True)
class DeploymentObservationReceipt:
    operation_id: str
    source_commit: str
    source_tree: str
    target_digest: str
    artifact_digest: str
    configuration_digest: str
    provider_id: str
    provider_evidence_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    external_to_repository: bool
    fixture: bool
    signature: str = ""


@dataclass(frozen=True)
class RollbackRehearsalReceipt:
    operation_id: str
    source_commit: str
    source_tree: str
    target_digest: str
    predecessor_artifact_digest: str
    backup_digest: str
    restored_snapshot_digest: str
    recovery_report_digest: str
    provider_id: str
    provider_evidence_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    external_to_repository: bool
    fixture: bool
    passed: bool
    signature: str = ""


@dataclass(frozen=True)
class OperatorAcceptanceReceipt:
    source_commit: str
    source_tree: str
    target_digest: str
    deployment_receipt_digest: str
    rollback_receipt_digest: str
    production_evidence_bundle_digest: str
    provider_set_digest: str
    operator_id: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    accepted: bool
    signature: str = ""


@dataclass(frozen=True)
class ProductionAcceptanceDecision:
    provider_set_digest: str
    production_evidence_bundle_digest: str
    deployment_receipt_digest: str
    rollback_receipt_digest: str
    operator_acceptance_digest: str
    target_digest: str
    deployment_accepted: bool
    production_implementation: bool = False
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


@runtime_checkable
class DistributedFenceProvider(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class ImmutableAuditLogProvider(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class KeyCustodyProvider(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class CompletionObserver(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class TerminalIntegrationObserver(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class SemanticReviewAuthority(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class DeploymentController(Protocol):
    descriptor: ExternalProviderDescriptor


@runtime_checkable
class OperatorAcceptanceAuthority(Protocol):
    descriptor: ExternalProviderDescriptor


def _git_oid(value: str, label: str) -> None:
    if not isinstance(value, str) or _GIT_OID.fullmatch(value) is None:
        raise EngineeringError(label)


def _verify_descriptor(value: ExternalProviderDescriptor, role: str) -> None:
    if not isinstance(value, ExternalProviderDescriptor):
        raise EngineeringError("external_provider_descriptor_required")
    checked_id(value.provider_id, "external_provider_id")
    checked_id(value.trust_domain, "external_provider_trust_domain")
    checked_id(value.signing_identity, "external_provider_signing_identity")
    checked_sha256(value.configuration_digest, "external_provider_configuration_digest")
    if value.role != role:
        raise EngineeringError("external_provider_role_mismatch")
    if value.endpoint_scheme not in _ALLOWED_SCHEMES:
        raise EngineeringError("external_provider_scheme")
    if value.fixture or not value.external_to_repository:
        raise EngineeringError("external_provider_not_independent")


def verify_production_provider_set(providers: ProductionProviderSet) -> str:
    if not isinstance(providers, ProductionProviderSet):
        raise EngineeringError("production_provider_set_required")
    values = tuple(getattr(providers, role) for role in _REQUIRED_PROVIDER_ROLES)
    for role, value in zip(_REQUIRED_PROVIDER_ROLES, values, strict=True):
        _verify_descriptor(value, role)
    provider_ids = tuple(value.provider_id for value in values)
    if len(set(provider_ids)) != len(provider_ids):
        raise EngineeringError("production_provider_role_collision")
    # Custody, observation, semantic review, deployment and operator acceptance
    # may not collapse onto one signing identity or one trust domain.
    separated = (
        providers.key_custody,
        providers.completion_observer,
        providers.terminal_integration_observer,
        providers.semantic_review,
        providers.deployment_controller,
        providers.operator_acceptance,
    )
    if len({value.signing_identity for value in separated}) != len(separated):
        raise EngineeringError("production_provider_signing_identity_collision")
    if len({value.trust_domain for value in separated}) != len(separated):
        raise EngineeringError("production_provider_trust_domain_collision")
    return semantic_digest(asdict(providers))


def verify_production_evidence_bundle(
    bundle: ProductionEvidenceBundle,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    provider_set_digest: str,
) -> str:
    if not isinstance(bundle, ProductionEvidenceBundle):
        raise EngineeringError("production_evidence_bundle_required")
    _git_oid(expected_source_commit, "production_evidence_source_commit")
    _git_oid(expected_source_tree, "production_evidence_source_tree")
    checked_sha256(expected_target_digest, "production_evidence_target_digest")
    checked_sha256(provider_set_digest, "production_evidence_provider_set_digest")
    if (
        bundle.source_commit != expected_source_commit
        or bundle.source_tree != expected_source_tree
        or bundle.target_digest != expected_target_digest
        or bundle.provider_set_digest != provider_set_digest
    ):
        raise EngineeringError("production_evidence_bundle_binding")
    digest_fields = (
        bundle.product_receipt_pair_digest,
        bundle.post_merge_main_receipt_digest,
        bundle.strong_sandbox_receipt_digest,
        bundle.distributed_fence_receipt_digest,
        bundle.immutable_audit_anchor_digest,
        bundle.source_key_custody_digest,
        bundle.ci_key_custody_digest,
        bundle.review_key_custody_digest,
        bundle.integration_key_custody_digest,
        bundle.completion_observation_digest,
        bundle.terminal_observation_digest,
        bundle.independent_review_digest,
        bundle.backup_digest,
        bundle.recovery_report_digest,
    )
    for index, value in enumerate(digest_fields):
        checked_sha256(value, f"production_evidence_digest_{index}")
    custody = (
        bundle.source_key_custody_digest,
        bundle.ci_key_custody_digest,
        bundle.review_key_custody_digest,
        bundle.integration_key_custody_digest,
    )
    if len(set(custody)) != len(custody):
        raise EngineeringError("production_evidence_key_custody_collision")
    return semantic_digest(asdict(bundle))


def verify_deployment_observation(
    receipt: DeploymentObservationReceipt,
    provider: ExternalProviderDescriptor,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, DeploymentObservationReceipt):
        raise EngineeringError("deployment_observation_required")
    _verify_descriptor(provider, "deployment_controller")
    _git_oid(expected_source_commit, "deployment_source_commit")
    _git_oid(expected_source_tree, "deployment_source_tree")
    checked_sha256(expected_target_digest, "deployment_target_digest")
    for value, label in (
        (receipt.target_digest, "deployment_target_digest"),
        (receipt.artifact_digest, "deployment_artifact_digest"),
        (receipt.configuration_digest, "deployment_configuration_digest"),
        (receipt.provider_evidence_digest, "deployment_provider_evidence_digest"),
    ):
        checked_sha256(value, label)
    checked_id(receipt.operation_id, "deployment_operation_id")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.target_digest != expected_target_digest
        or receipt.provider_id != provider.provider_id
        or receipt.configuration_digest != provider.configuration_digest
        or receipt.signing_identity != provider.signing_identity
        or receipt.issuer != "deployment_observer"
        or receipt.fixture
        or not receipt.external_to_repository
    ):
        raise EngineeringError("deployment_observation_binding")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="deployment_observation_stale",
    )
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("deployment_observation_signature")
    return semantic_digest(asdict(receipt))


def verify_rollback_rehearsal(
    receipt: RollbackRehearsalReceipt,
    provider: ExternalProviderDescriptor,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, RollbackRehearsalReceipt):
        raise EngineeringError("rollback_rehearsal_required")
    _verify_descriptor(provider, "deployment_controller")
    _git_oid(expected_source_commit, "rollback_source_commit")
    _git_oid(expected_source_tree, "rollback_source_tree")
    checked_sha256(expected_target_digest, "rollback_target_digest")
    for value, label in (
        (receipt.predecessor_artifact_digest, "rollback_predecessor_digest"),
        (receipt.backup_digest, "rollback_backup_digest"),
        (receipt.restored_snapshot_digest, "rollback_snapshot_digest"),
        (receipt.recovery_report_digest, "rollback_recovery_report_digest"),
        (receipt.provider_evidence_digest, "rollback_provider_evidence_digest"),
    ):
        checked_sha256(value, label)
    checked_id(receipt.operation_id, "rollback_operation_id")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.target_digest != expected_target_digest
        or receipt.provider_id != provider.provider_id
        or receipt.signing_identity != provider.signing_identity
        or receipt.issuer != "rollback_rehearsal_observer"
        or receipt.fixture
        or not receipt.external_to_repository
        or not receipt.passed
    ):
        raise EngineeringError("rollback_rehearsal_binding")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="rollback_rehearsal_stale",
    )
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("rollback_rehearsal_signature")
    return semantic_digest(asdict(receipt))


def verify_operator_acceptance(
    receipt: OperatorAcceptanceReceipt,
    provider: ExternalProviderDescriptor,
    deployment_receipt_digest: str,
    rollback_receipt_digest: str,
    production_evidence_bundle_digest: str,
    provider_set_digest: str,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, OperatorAcceptanceReceipt):
        raise EngineeringError("operator_acceptance_required")
    _verify_descriptor(provider, "operator_acceptance")
    _git_oid(expected_source_commit, "operator_acceptance_source_commit")
    _git_oid(expected_source_tree, "operator_acceptance_source_tree")
    for value, label in (
        (expected_target_digest, "operator_acceptance_target_digest"),
        (deployment_receipt_digest, "operator_acceptance_deployment_digest"),
        (rollback_receipt_digest, "operator_acceptance_rollback_digest"),
        (provider_set_digest, "operator_acceptance_provider_set_digest"),
        (production_evidence_bundle_digest, "operator_acceptance_bundle_digest"),
    ):
        checked_sha256(value, label)
    checked_id(receipt.operator_id, "operator_id")
    checked_id(receipt.signing_identity, "operator_signing_identity")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.target_digest != expected_target_digest
        or receipt.deployment_receipt_digest != deployment_receipt_digest
        or receipt.rollback_receipt_digest != rollback_receipt_digest
        or receipt.provider_set_digest != provider_set_digest
        or receipt.production_evidence_bundle_digest
        != production_evidence_bundle_digest
        or receipt.signing_identity != provider.signing_identity
        or receipt.issuer != "operator_acceptance_authority"
        or not receipt.accepted
    ):
        raise EngineeringError("operator_acceptance_binding")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="operator_acceptance_stale",
    )
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("operator_acceptance_signature")
    return semantic_digest(asdict(receipt))


def verify_production_acceptance_bundle(
    providers: ProductionProviderSet,
    evidence: ProductionEvidenceBundle,
    deployment: DeploymentObservationReceipt,
    rollback: RollbackRehearsalReceipt,
    acceptance: OperatorAcceptanceReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> ProductionAcceptanceDecision:
    provider_set_digest = verify_production_provider_set(providers)
    evidence_digest = verify_production_evidence_bundle(
        evidence,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        expected_target_digest=expected_target_digest,
        provider_set_digest=provider_set_digest,
    )
    deployment_digest = verify_deployment_observation(
        deployment,
        providers.deployment_controller,
        trust_store,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        expected_target_digest=expected_target_digest,
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    rollback_digest = verify_rollback_rehearsal(
        rollback,
        providers.deployment_controller,
        trust_store,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        expected_target_digest=expected_target_digest,
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    acceptance_digest = verify_operator_acceptance(
        acceptance,
        providers.operator_acceptance,
        deployment_digest,
        rollback_digest,
        evidence_digest,
        provider_set_digest,
        trust_store,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        expected_target_digest=expected_target_digest,
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    return ProductionAcceptanceDecision(
        provider_set_digest=provider_set_digest,
        production_evidence_bundle_digest=evidence_digest,
        deployment_receipt_digest=deployment_digest,
        rollback_receipt_digest=rollback_digest,
        operator_acceptance_digest=acceptance_digest,
        target_digest=expected_target_digest,
        deployment_accepted=True,
        # Acceptance evidence is consumed by an external release authority. The
        # module itself never flips its canonical production claim.
        production_implementation=False,
    )
