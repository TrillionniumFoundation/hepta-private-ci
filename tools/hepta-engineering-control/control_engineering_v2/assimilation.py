"""Consent-bound, non-propagating external-system assimilation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from collections.abc import Iterable, Mapping

from .control_plane import (
    EngineeringError,
    bounded_tuple,
    checked_id,
    checked_sha256,
    semantic_digest,
)

READ_ONLY_OPERATIONS = frozenset({"query_version", "query_health", "read_status"})
DENIED_OPERATIONS = frozenset(
    {
        "install_package",
        "remove_package",
        "write_configuration",
        "start_service",
        "stop_service",
        "enable_service",
        "register_peer",
        "copy_credential",
        "escalate_privilege",
        "activate_production",
    }
)


@dataclass(frozen=True)
class OwnerConsentReceipt:
    owner_principal: str
    target_identity_digest: str
    allowed_operations: tuple[str, ...]
    allowed_roots: tuple[str, ...]
    observed_unix_ns: int
    expires_unix_ns: int
    receipt_digest: str


@dataclass(frozen=True)
class ExternalManifestCandidate:
    target_identity_digest: str
    os_id: str
    os_version: str
    package_inventory_digest: str
    service_graph_digest: str
    mutable_state_digest: str
    provenance_digest: str
    omissions: tuple[str, ...]
    raw_secrets_copied: bool = False
    authority_granted: bool = False


@dataclass(frozen=True)
class TypedOperation:
    operation_id: str
    operation_class: str
    input_schema_digest: str
    output_schema_digest: str
    deadline_millis: int
    maximum_output_bytes: int
    terminal_observer: str
    idempotency: str
    external_effect: bool = False


@dataclass(frozen=True)
class SandboxParityReceipt:
    target_identity_digest: str
    manifest_digest: str
    operations_digest: str
    exact_fixture_digest: str
    fault_results_digest: str
    rollback_digest: str
    evaluator_principal: str
    generator_principal: str
    passed: bool
    network_unrestricted: bool = False
    production_credentials_exposed: bool = False
    authority_delta: bool = False


@dataclass(frozen=True)
class AssimilationProposal:
    proposal_id: str
    target_identity_digest: str
    consent_receipt_digest: str
    manifest_digest: str
    operations_digest: str
    sandbox_receipt_digest: str
    state: str
    activation: bool = False
    federation: bool = False
    propagation: bool = False
    authority_granted: bool = False


def validate_consent(
    receipt: OwnerConsentReceipt,
    *,
    now_ns: int | None = None,
) -> OwnerConsentReceipt:
    now = time.time_ns() if now_ns is None else now_ns
    if (
        type(receipt.observed_unix_ns) is not int
        or type(receipt.expires_unix_ns) is not int
        or not receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("consent_expired")
    operations = tuple(
        sorted(
            {
                checked_id(value, "invalid_operation")
                for value in receipt.allowed_operations
            }
        )
    )
    if not operations or not set(operations).issubset(READ_ONLY_OPERATIONS):
        raise EngineeringError("consent_scope_widens_authority")
    if set(operations) & DENIED_OPERATIONS:
        raise EngineeringError("denied_assimilation_operation")
    roots = tuple(
        sorted(
            {
                checked_id(value, "invalid_root_reference")
                for value in receipt.allowed_roots
            }
        )
    )
    if not roots:
        raise EngineeringError("empty_consent_scope")
    checked_sha256(receipt.target_identity_digest, "invalid_target_identity")
    checked_sha256(receipt.receipt_digest, "invalid_consent_digest")
    return OwnerConsentReceipt(
        checked_id(receipt.owner_principal, "invalid_owner_principal"),
        receipt.target_identity_digest,
        operations,
        roots,
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        receipt.receipt_digest,
    )


def build_manifest_candidate(
    consent: OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    *,
    now_ns: int | None = None,
) -> ExternalManifestCandidate:
    value = validate_consent(consent, now_ns=now_ns)
    required = {
        "os_id",
        "os_version",
        "package_inventory_digest",
        "service_graph_digest",
        "mutable_state_digest",
        "provenance_digest",
    }
    if set(observations) != required:
        raise EngineeringError("manifest_observation_shape")
    for field in required - {"os_id", "os_version"}:
        checked_sha256(observations[field], "invalid_manifest_digest")
    if observations["os_id"] != "debian" or not observations["os_version"]:
        raise EngineeringError("unsupported_initial_target")
    omission_values = tuple(
        sorted(
            {
                checked_id(str(item), "invalid_omission")
                for item in bounded_tuple(omissions, 64, "omission_limit_exceeded")
            }
        )
    )
    return ExternalManifestCandidate(
        value.target_identity_digest,
        observations["os_id"],
        observations["os_version"],
        observations["package_inventory_digest"],
        observations["service_graph_digest"],
        observations["mutable_state_digest"],
        observations["provenance_digest"],
        omission_values,
    )


def synthesize_read_only_contracts(
    consent: OwnerConsentReceipt,
    manifest: ExternalManifestCandidate,
    *,
    now_ns: int | None = None,
) -> tuple[TypedOperation, ...]:
    value = validate_consent(consent, now_ns=now_ns)
    if manifest.target_identity_digest != value.target_identity_digest:
        raise EngineeringError("target_identity_drift")
    manifest_digest = semantic_digest(asdict(manifest))
    result: list[TypedOperation] = []
    for name in value.allowed_operations:
        body = {
            "target": value.target_identity_digest,
            "operation": name,
            "manifest": manifest_digest,
        }
        result.append(
            TypedOperation(
                semantic_digest(body)[:32],
                name,
                semantic_digest(
                    {"operation": name, "direction": "input", "version": 1}
                ),
                semantic_digest(
                    {"operation": name, "direction": "output", "version": 1}
                ),
                5_000,
                65_536,
                "explicit_target_adapter",
                "read_only_repeatable",
            )
        )
    return tuple(result)


def propose_dormant_assimilation(
    consent: OwnerConsentReceipt,
    manifest: ExternalManifestCandidate,
    operations: Iterable[TypedOperation],
    sandbox: SandboxParityReceipt,
    *,
    now_ns: int | None = None,
) -> AssimilationProposal:
    value = validate_consent(consent, now_ns=now_ns)
    raw_operations = bounded_tuple(operations, 16, "operation_limit_exceeded")
    if not raw_operations or any(
        not isinstance(item, TypedOperation) for item in raw_operations
    ):
        raise EngineeringError("invalid_operation_set")
    operation_values = tuple(raw_operations)
    if (
        manifest.target_identity_digest != value.target_identity_digest
        or sandbox.target_identity_digest != value.target_identity_digest
    ):
        raise EngineeringError("target_identity_drift")
    manifest_digest = semantic_digest(asdict(manifest))
    operations_digest = semantic_digest([asdict(item) for item in operation_values])
    if (
        sandbox.manifest_digest != manifest_digest
        or sandbox.operations_digest != operations_digest
    ):
        raise EngineeringError("sandbox_input_drift")
    if sandbox.evaluator_principal == sandbox.generator_principal:
        raise EngineeringError("evaluator_identity_collision")
    if sandbox.passed is not True:
        raise EngineeringError("sandbox_parity_failed")
    if (
        sandbox.network_unrestricted
        or sandbox.production_credentials_exposed
        or sandbox.authority_delta
    ):
        raise EngineeringError("sandbox_boundary_violation")
    if any(
        item.external_effect or item.operation_class not in READ_ONLY_OPERATIONS
        for item in operation_values
    ):
        raise EngineeringError("operation_widens_authority")
    for digest in (
        sandbox.exact_fixture_digest,
        sandbox.fault_results_digest,
        sandbox.rollback_digest,
    ):
        checked_sha256(digest, "invalid_sandbox_digest")
    sandbox_digest = semantic_digest(asdict(sandbox))
    body = {
        "target": value.target_identity_digest,
        "consent": value.receipt_digest,
        "manifest": manifest_digest,
        "operations": operations_digest,
        "sandbox": sandbox_digest,
    }
    return AssimilationProposal(
        semantic_digest(body)[:32],
        value.target_identity_digest,
        value.receipt_digest,
        manifest_digest,
        operations_digest,
        sandbox_digest,
        "dormant_candidate",
    )
