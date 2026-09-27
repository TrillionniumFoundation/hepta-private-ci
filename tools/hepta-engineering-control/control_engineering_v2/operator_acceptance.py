"""Externally signed operator acceptance for a target-host deployment candidate."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .clock import Clock, ClockPolicy, validate_observation_window
from .control_plane import EngineeringError, checked_id, checked_sha256, semantic_digest
from .evidence import SignatureTrustStore


@dataclass(frozen=True)
class OperatorAcceptanceReceipt:
    target_id: str
    source_commit: str
    source_tree: str
    provider_bundle_digest: str
    recovery_rehearsal_digest: str
    capacity_policy_digest: str
    capacity_observation_digest: str
    canary_observation_digest: str
    independent_review_digest: str
    deployment_observed: bool
    rollback_rehearsed: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    merge_authority: bool = False
    release_authority: bool = False


def operator_acceptance_digest(receipt: OperatorAcceptanceReceipt) -> str:
    if not isinstance(receipt, OperatorAcceptanceReceipt):
        raise EngineeringError("operator_acceptance_required")
    return semantic_digest(asdict(receipt))


def verify_operator_acceptance(
    receipt: OperatorAcceptanceReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    expected_target_id: str,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_provider_bundle_digest: str,
    expected_recovery_rehearsal_digest: str,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, OperatorAcceptanceReceipt):
        raise EngineeringError("operator_acceptance_required")
    checked_id(receipt.target_id, "target_id")
    checked_id(receipt.issuer, "issuer")
    checked_id(receipt.signing_identity, "signing_identity")
    if receipt.issuer != "control_engineering_operator":
        raise EngineeringError("operator_acceptance_issuer")
    if (
        receipt.target_id != expected_target_id
        or receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.provider_bundle_digest != expected_provider_bundle_digest
        or receipt.recovery_rehearsal_digest
        != expected_recovery_rehearsal_digest
    ):
        raise EngineeringError("operator_acceptance_binding")
    if receipt.deployment_observed is not True or receipt.rollback_rehearsed is not True:
        raise EngineeringError("operator_acceptance_incomplete")
    if receipt.merge_authority is not False or receipt.release_authority is not False:
        raise EngineeringError("operator_acceptance_authority_escalation")
    for value, label in (
        (receipt.provider_bundle_digest, "provider_bundle_digest"),
        (receipt.recovery_rehearsal_digest, "recovery_rehearsal_digest"),
        (receipt.capacity_policy_digest, "capacity_policy_digest"),
        (receipt.capacity_observation_digest, "capacity_observation_digest"),
        (receipt.canary_observation_digest, "canary_observation_digest"),
        (receipt.independent_review_digest, "independent_review_digest"),
    ):
        checked_sha256(value, label)
        if value == "0" * 64:
            raise EngineeringError("operator_acceptance_digest")
    validate_observation_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("operator_acceptance_signature")
    return operator_acceptance_digest(receipt)
