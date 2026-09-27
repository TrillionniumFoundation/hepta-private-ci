"""Fail-closed command adapters for externally governed production providers.

The repository cannot manufacture distributed consensus, an immutable audit log,
HSM custody, CI completion, or terminal integration observation.  This module
provides one bounded JSON-over-stdin adapter for real provider CLIs on an admitted
host.  It never invokes a shell, never inherits ambient secrets, and rejects
fixture/test/mock provider identities in production mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import subprocess
from typing import Any, TypeVar

from .audit_checkpoint import AuditCheckpointReceipt, checkpoint_receipt_digest
from .control_plane import (
    EngineeringError,
    canonical_json,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .external_controls import (
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
)
from .integration_controller import IntegrationTerminalReceipt
from .orchestration import CompletionReceipt


_PROVIDER_SCHEMA = "hepta.control-engineering-provider-response.v1"
_FORBIDDEN_PROVIDER_MARKERS = ("fixture", "test", "mock", "dummy", "example")
T = TypeVar("T")


@dataclass(frozen=True)
class ProviderCommand:
    provider_id: str
    executable: str
    arguments: tuple[str, ...] = ()
    timeout_seconds: int = 30
    maximum_output_bytes: int = 1_048_576
    production: bool = True

    def __post_init__(self) -> None:
        checked_id(self.provider_id, "provider_id")
        executable = Path(self.executable)
        if not executable.is_absolute():
            raise EngineeringError("provider_executable_not_absolute")
        if any(
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or len(value.encode("utf-8")) > 4096
            for value in self.arguments
        ):
            raise EngineeringError("provider_arguments_invalid")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 300:
            raise EngineeringError("provider_timeout_invalid")
        if (
            type(self.maximum_output_bytes) is not int
            or not 1024 <= self.maximum_output_bytes <= 16 * 1_048_576
        ):
            raise EngineeringError("provider_output_bound_invalid")
        lowered = self.provider_id.casefold()
        if self.production and any(marker in lowered for marker in _FORBIDDEN_PROVIDER_MARKERS):
            raise EngineeringError("production_fixture_provider_forbidden")


@dataclass(frozen=True)
class AuditPublicationReceipt:
    provider_id: str
    checkpoint_digest: str
    log_id: str
    log_sequence: int
    inclusion_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


class ProviderTrustStore:
    """Signature port backed by an admitted external signer/verifier command."""

    def __init__(
        self,
        command: ProviderCommand,
        *,
        environment: dict[str, str] | None = None,
    ):
        if not isinstance(command, ProviderCommand):
            raise EngineeringError("provider_command_required")
        self.command = command
        self.environment = dict(environment or {})

    @staticmethod
    def _payload(value: object) -> object:
        if hasattr(value, "__dataclass_fields__"):
            row = asdict(value)
        else:
            row = value
        if isinstance(row, dict):
            row = dict(row)
            row.pop("signature", None)
        return row

    def sign(self, value: object, issuer: str, signing_identity: str) -> str:
        payload, _ = invoke_provider(
            self.command,
            "sign_typed_receipt",
            {
                "issuer": issuer,
                "signingIdentity": signing_identity,
                "payload": self._payload(value),
            },
            environment=self.environment,
        )
        if set(payload) != {"signature"} or not isinstance(payload["signature"], str):
            raise EngineeringError("provider_signature_payload")
        return payload["signature"]

    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool:
        payload, _ = invoke_provider(
            self.command,
            "verify_typed_receipt",
            {
                "issuer": issuer,
                "signingIdentity": signing_identity,
                "payload": self._payload(value),
                "signature": signature,
            },
            environment=self.environment,
        )
        if set(payload) != {"valid"} or type(payload["valid"]) is not bool:
            raise EngineeringError("provider_signature_payload")
        return bool(payload["valid"])


@dataclass(frozen=True)
class ExternalProductionEvidenceBundle:
    distributed_revocation_frontier: DistributedRevocationFrontierReceipt
    distributed_fence: DistributedFenceReceipt
    audit_publication: AuditPublicationReceipt
    key_custody: tuple[KeyCustodyReceipt, ...]
    completion: CompletionReceipt
    terminal_observation: IntegrationTerminalReceipt
    provider_request_digests: tuple[tuple[str, str], ...]
    bundle_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    deployment_authority: bool = False
    release_authority: bool = False


def _safe_environment(extra: dict[str, str] | None) -> dict[str, str]:
    result = {"LANG": "C", "LC_ALL": "C", "PYTHONIOENCODING": "utf-8", "PATH": "/usr/bin:/bin"}
    if extra is None:
        return result
    for key, value in extra.items():
        if (
            not isinstance(key, str)
            or not key.startswith("HEPTA_PROVIDER_")
            or not isinstance(value, str)
            or "\x00" in key
            or "\x00" in value
            or len(key.encode("utf-8")) > 128
            or len(value.encode("utf-8")) > 16_384
        ):
            raise EngineeringError("provider_environment_invalid")
        result[key] = value
    return result


def invoke_provider(
    command: ProviderCommand,
    operation: str,
    request: dict[str, object],
    *,
    environment: dict[str, str] | None = None,
) -> tuple[dict[str, object], str]:
    if not isinstance(command, ProviderCommand):
        raise EngineeringError("provider_command_required")
    checked_id(operation, "provider_operation")
    if not isinstance(request, dict):
        raise EngineeringError("provider_request_invalid")
    request_body = {
        "schema": "hepta.control-engineering-provider-request.v1",
        "providerId": command.provider_id,
        "operation": operation,
        "request": request,
    }
    request_digest = semantic_digest(request_body)
    body = canonical_json({**request_body, "requestDigest": request_digest}) + b"\n"
    try:
        process = subprocess.run(
            [command.executable, *command.arguments],
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_safe_environment(environment),
            timeout=command.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise EngineeringError("provider_timeout") from None
    except OSError:
        raise EngineeringError("provider_unavailable") from None
    if len(process.stdout) > command.maximum_output_bytes:
        raise EngineeringError("provider_output_limit")
    if process.returncode != 0:
        # Raw provider stderr can contain credentials or target details.  Never
        # include it in the stable error surface.
        raise EngineeringError("provider_rejected")
    try:
        response = json.loads(process.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError("provider_response_invalid") from None
    if not isinstance(response, dict) or set(response) != {
        "schema",
        "providerId",
        "operation",
        "requestDigest",
        "payload",
    }:
        raise EngineeringError("provider_response_invalid")
    if (
        response["schema"] != _PROVIDER_SCHEMA
        or response["providerId"] != command.provider_id
        or response["operation"] != operation
        or response["requestDigest"] != request_digest
        or not isinstance(response["payload"], dict)
    ):
        raise EngineeringError("provider_response_binding")
    return response["payload"], request_digest


def _typed_payload(cls: type[T], value: object, code: str) -> T:
    if not isinstance(value, dict):
        raise EngineeringError(code)
    expected = {field.name for field in fields(cls)}
    if set(value) != expected:
        raise EngineeringError(code)
    try:
        return cls(**value)
    except (TypeError, ValueError):
        raise EngineeringError(code) from None


def collect_external_production_evidence(
    *,
    distributed_lease_provider: ProviderCommand,
    immutable_audit_provider: ProviderCommand,
    key_custody_provider: ProviderCommand,
    completion_observer: ProviderCommand,
    terminal_observer: ProviderCommand,
    checkpoint: AuditCheckpointReceipt,
    distributed_request: dict[str, object],
    key_custody_request: dict[str, object],
    completion_request: dict[str, object],
    terminal_request: dict[str, object],
    environment_by_provider: dict[str, dict[str, str]] | None = None,
) -> ExternalProductionEvidenceBundle:
    commands = (
        distributed_lease_provider,
        immutable_audit_provider,
        key_custody_provider,
        completion_observer,
        terminal_observer,
    )
    ids = tuple(command.provider_id for command in commands)
    if len(set(ids)) != len(ids):
        raise EngineeringError("provider_role_collision")
    environments = environment_by_provider or {}

    lease_payload, lease_request_digest = invoke_provider(
        distributed_lease_provider,
        "observe_distributed_fence",
        distributed_request,
        environment=environments.get(distributed_lease_provider.provider_id),
    )
    if set(lease_payload) != {"revocationFrontier", "fence"}:
        raise EngineeringError("distributed_provider_payload")
    frontier = _typed_payload(
        DistributedRevocationFrontierReceipt,
        lease_payload["revocationFrontier"],
        "distributed_provider_payload",
    )
    fence = _typed_payload(
        DistributedFenceReceipt,
        lease_payload["fence"],
        "distributed_provider_payload",
    )

    audit_payload, audit_request_digest = invoke_provider(
        immutable_audit_provider,
        "append_audit_checkpoint",
        {
            "checkpoint": asdict(checkpoint),
            "checkpointDigest": checkpoint_receipt_digest(checkpoint),
        },
        environment=environments.get(immutable_audit_provider.provider_id),
    )
    audit_publication = _typed_payload(
        AuditPublicationReceipt,
        audit_payload,
        "audit_provider_payload",
    )
    if audit_publication.provider_id != immutable_audit_provider.provider_id:
        raise EngineeringError("audit_provider_payload")
    checked_sha256(audit_publication.checkpoint_digest, "checkpoint_digest")
    if audit_publication.checkpoint_digest != checkpoint_receipt_digest(checkpoint):
        raise EngineeringError("audit_provider_checkpoint_mismatch")

    custody_payload, custody_request_digest = invoke_provider(
        key_custody_provider,
        "attest_key_custody",
        key_custody_request,
        environment=environments.get(key_custody_provider.provider_id),
    )
    custody_rows = custody_payload.get("receipts")
    if set(custody_payload) != {"receipts"} or not isinstance(custody_rows, list):
        raise EngineeringError("key_custody_provider_payload")
    custody = tuple(
        _typed_payload(KeyCustodyReceipt, row, "key_custody_provider_payload")
        for row in custody_rows
    )
    if not custody:
        raise EngineeringError("key_custody_provider_payload")

    completion_payload, completion_request_digest = invoke_provider(
        completion_observer,
        "observe_ci_completion",
        completion_request,
        environment=environments.get(completion_observer.provider_id),
    )
    completion = _typed_payload(
        CompletionReceipt, completion_payload, "completion_provider_payload"
    )

    terminal_payload, terminal_request_digest = invoke_provider(
        terminal_observer,
        "observe_integration_terminal",
        terminal_request,
        environment=environments.get(terminal_observer.provider_id),
    )
    terminal = _typed_payload(
        IntegrationTerminalReceipt,
        terminal_payload,
        "terminal_provider_payload",
    )

    request_digests = tuple(
        sorted(
            (
                (distributed_lease_provider.provider_id, lease_request_digest),
                (immutable_audit_provider.provider_id, audit_request_digest),
                (key_custody_provider.provider_id, custody_request_digest),
                (completion_observer.provider_id, completion_request_digest),
                (terminal_observer.provider_id, terminal_request_digest),
            )
        )
    )
    body = {
        "distributedRevocationFrontier": asdict(frontier),
        "distributedFence": asdict(fence),
        "auditPublication": asdict(audit_publication),
        "keyCustody": tuple(asdict(item) for item in custody),
        "completion": asdict(completion),
        "terminalObservation": asdict(terminal),
        "providerRequestDigests": request_digests,
    }
    return ExternalProductionEvidenceBundle(
        distributed_revocation_frontier=frontier,
        distributed_fence=fence,
        audit_publication=audit_publication,
        key_custody=custody,
        completion=completion,
        terminal_observation=terminal,
        provider_request_digests=request_digests,
        bundle_digest=semantic_digest(body),
    )
