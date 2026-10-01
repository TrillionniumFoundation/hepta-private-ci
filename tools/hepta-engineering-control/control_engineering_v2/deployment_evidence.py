"""Externally signed deployment, recovery, rollback and operator evidence.

These contracts verify observations produced outside control.engineering. They do
not deploy a target, operate a backup system, approve a release, or change the
canonical production_implementation fact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time

from .control_plane import (
    EngineeringError,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .time_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_SKEW_POLICY,
    validate_signed_window,
)


@dataclass(frozen=True)
class TargetDeploymentReceipt:
    target_id: str
    environment: str
    source_commit: str
    source_tree: str
    artifact_digest: str
    owner_snapshot_digest: str
    passed: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class BackupRecoveryReceipt:
    target_id: str
    source_commit: str
    source_tree: str
    backup_digest: str
    expected_owner_snapshot_digest: str
    restored_owner_snapshot_digest: str
    integrity_verified: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class RollbackRehearsalReceipt:
    target_id: str
    deployed_source_commit: str
    predecessor_commit: str
    predecessor_tree: str
    restored_owner_snapshot_digest: str
    rollback_succeeded: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class OperatorAcceptanceReceipt:
    target_id: str
    operator_id: str
    deployment_receipt_digest: str
    recovery_receipt_digest: str
    rollback_receipt_digest: str
    accepted: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class ProductionAcceptanceDecision:
    deployment_verified: bool
    recovery_verified: bool
    rollback_verified: bool
    operator_acceptance_verified: bool
    evidence_digest: str
    production_implementation: bool = False
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _git_sha(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
        or value == "0" * 40
    ):
        raise EngineeringError("invalid_" + label)
    return value


def _verify_receipt(
    value: (
        TargetDeploymentReceipt
        | BackupRecoveryReceipt
        | RollbackRehearsalReceipt
        | OperatorAcceptanceReceipt
    ),
    expected_type: type,
    expected_issuer: str,
    trust_store: SignatureTrustStore,
    now: int,
    policy: ClockSkewPolicy,
) -> str:
    if not isinstance(value, expected_type):
        raise EngineeringError("production_evidence_type")
    issuer = getattr(value, "issuer")
    identity = getattr(value, "signing_identity")
    checked_id(identity, "signing_identity")
    if issuer != expected_issuer:
        raise EngineeringError("production_evidence_issuer_role")
    validate_signed_window(
        getattr(value, "observed_unix_ns"),
        getattr(value, "expires_unix_ns"),
        now,
        policy=policy,
    )
    if not trust_store.verify(value, issuer, identity, getattr(value, "signature")):
        raise EngineeringError("production_evidence_signature")
    return semantic_digest(asdict(value))


def verify_production_acceptance_evidence(
    deployment: TargetDeploymentReceipt,
    recovery: BackupRecoveryReceipt,
    rollback: RollbackRehearsalReceipt,
    operator: OperatorAcceptanceReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,
) -> ProductionAcceptanceDecision:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    deployment_digest = _verify_receipt(
        deployment,
        TargetDeploymentReceipt,
        "target_deployment_observer",
        trust_store,
        now,
        clock_policy,
    )
    recovery_digest = _verify_receipt(
        recovery,
        BackupRecoveryReceipt,
        "backup_recovery_observer",
        trust_store,
        now,
        clock_policy,
    )
    rollback_digest = _verify_receipt(
        rollback,
        RollbackRehearsalReceipt,
        "rollback_rehearsal_observer",
        trust_store,
        now,
        clock_policy,
    )
    operator_digest = _verify_receipt(
        operator,
        OperatorAcceptanceReceipt,
        "operator_acceptance_authority",
        trust_store,
        now,
        clock_policy,
    )
    identities = {
        deployment.signing_identity,
        recovery.signing_identity,
        rollback.signing_identity,
        operator.signing_identity,
    }
    if len(identities) != 4:
        raise EngineeringError("production_evidence_role_collision")
    target = checked_id(deployment.target_id, "target_id")
    checked_id(deployment.environment, "environment")
    checked_id(operator.operator_id, "operator_id")
    if recovery.target_id != target or rollback.target_id != target or operator.target_id != target:
        raise EngineeringError("production_evidence_target_mismatch")
    source_commit = _git_sha(deployment.source_commit, "source_commit")
    source_tree = _git_sha(deployment.source_tree, "source_tree")
    if recovery.source_commit != source_commit or recovery.source_tree != source_tree:
        raise EngineeringError("production_evidence_source_mismatch")
    if rollback.deployed_source_commit != source_commit:
        raise EngineeringError("production_evidence_rollback_source_mismatch")
    _git_sha(rollback.predecessor_commit, "predecessor_commit")
    _git_sha(rollback.predecessor_tree, "predecessor_tree")
    if rollback.predecessor_commit == source_commit:
        raise EngineeringError("production_evidence_rollback_predecessor")
    for value, label in (
        (deployment.artifact_digest, "artifact_digest"),
        (deployment.owner_snapshot_digest, "owner_snapshot_digest"),
        (recovery.backup_digest, "backup_digest"),
        (recovery.expected_owner_snapshot_digest, "expected_owner_snapshot_digest"),
        (recovery.restored_owner_snapshot_digest, "restored_owner_snapshot_digest"),
        (rollback.restored_owner_snapshot_digest, "rollback_owner_snapshot_digest"),
        (operator.deployment_receipt_digest, "deployment_receipt_digest"),
        (operator.recovery_receipt_digest, "recovery_receipt_digest"),
        (operator.rollback_receipt_digest, "rollback_receipt_digest"),
    ):
        checked_sha256(value, label)
        if value == "0" * 64:
            raise EngineeringError("invalid_" + label)
    if (
        recovery.expected_owner_snapshot_digest != deployment.owner_snapshot_digest
        or recovery.restored_owner_snapshot_digest != deployment.owner_snapshot_digest
        or rollback.restored_owner_snapshot_digest != deployment.owner_snapshot_digest
    ):
        raise EngineeringError("production_evidence_snapshot_mismatch")
    if (
        operator.deployment_receipt_digest != deployment_digest
        or operator.recovery_receipt_digest != recovery_digest
        or operator.rollback_receipt_digest != rollback_digest
    ):
        raise EngineeringError("operator_acceptance_binding_mismatch")
    if not (
        deployment.passed is True
        and recovery.integrity_verified is True
        and rollback.rollback_succeeded is True
        and operator.accepted is True
    ):
        raise EngineeringError("production_evidence_negative_observation")
    evidence = {
        "targetId": target,
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "deploymentReceiptDigest": deployment_digest,
        "recoveryReceiptDigest": recovery_digest,
        "rollbackReceiptDigest": rollback_digest,
        "operatorReceiptDigest": operator_digest,
    }
    return ProductionAcceptanceDecision(
        True,
        True,
        True,
        True,
        semantic_digest(evidence),
    )
