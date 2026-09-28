"""Authenticated external-provider transport for production control evidence.

Repository fixtures can exercise receipt verification, but they cannot stand in
for distributed fencing, immutable audit storage, HSM/KMS custody, independent
completion observation, deployment, rollback, or operator acceptance. This
module supplies a bounded mTLS JSON transport and exact response binding so real
providers can deliver already-signed receipts without becoming a new local
authority source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import ssl
import time
from typing import Any, Protocol
from urllib.parse import urlsplit

from .control_plane import (
    EngineeringError,
    canonical_json,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
)
from .integration_controller import IntegrationTerminalReceipt
from .orchestration import CompletionReceipt

_MAX_RESPONSE_BYTES = 1_048_576
_MAX_REQUEST_BYTES = 262_144


@dataclass(frozen=True)
class ExternalProviderEndpoint:
    service: str
    url: str
    tls_certificate_sha256: str
    ca_file: str = ""
    client_certificate_file: str = ""
    client_private_key_file: str = ""
    timeout_seconds: int = 10
    maximum_response_bytes: int = _MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        checked_id(self.service, "external_provider_service")
        parts = urlsplit(self.url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or not parts.path.startswith("/")
        ):
            raise EngineeringError("external_provider_endpoint_invalid")
        checked_sha256(self.tls_certificate_sha256, "external_provider_tls_pin")
        if self.tls_certificate_sha256 == "0" * 64:
            raise EngineeringError("external_provider_tls_pin")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise EngineeringError("external_provider_timeout")
        if (
            type(self.maximum_response_bytes) is not int
            or not 1 <= self.maximum_response_bytes <= _MAX_RESPONSE_BYTES
        ):
            raise EngineeringError("external_provider_response_limit")
        if bool(self.client_certificate_file) != bool(self.client_private_key_file):
            raise EngineeringError("external_provider_client_identity_incomplete")
        for value in (
            self.ca_file,
            self.client_certificate_file,
            self.client_private_key_file,
        ):
            if not isinstance(value, str) or "\x00" in value:
                raise EngineeringError("external_provider_path_invalid")


class JsonTransport(Protocol):
    def post(self, endpoint: ExternalProviderEndpoint, body: bytes) -> bytes: ...


class HttpsJsonTransport:
    """No-redirect HTTPS transport with certificate pinning and bounded bodies."""

    def post(self, endpoint: ExternalProviderEndpoint, body: bytes) -> bytes:
        if not isinstance(endpoint, ExternalProviderEndpoint):
            raise EngineeringError("external_provider_endpoint_required")
        if not isinstance(body, bytes) or not body or len(body) > _MAX_REQUEST_BYTES:
            raise EngineeringError("external_provider_request_size")
        parts = urlsplit(endpoint.url)
        context = ssl.create_default_context(cafile=endpoint.ca_file or None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if endpoint.client_certificate_file:
            for path in (
                endpoint.client_certificate_file,
                endpoint.client_private_key_file,
            ):
                if not Path(path).is_file():
                    raise EngineeringError("external_provider_client_identity_missing")
            context.load_cert_chain(
                endpoint.client_certificate_file,
                endpoint.client_private_key_file,
            )
        connection = http.client.HTTPSConnection(
            parts.hostname,
            parts.port or 443,
            timeout=endpoint.timeout_seconds,
            context=context,
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise EngineeringError("external_provider_tls_unavailable")
            certificate = connection.sock.getpeercert(binary_form=True)
            if not certificate:
                raise EngineeringError("external_provider_tls_unavailable")
            if hashlib.sha256(certificate).hexdigest() != endpoint.tls_certificate_sha256:
                raise EngineeringError("external_provider_tls_pin_mismatch")
            connection.request(
                "POST",
                parts.path,
                body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "User-Agent": "hepta-control-engineering/1",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise EngineeringError("external_provider_http_status")
            if not response.getheader("Content-Type", "").lower().startswith(
                "application/json"
            ):
                raise EngineeringError("external_provider_content_type")
            payload = response.read(endpoint.maximum_response_bytes + 1)
            if len(payload) > endpoint.maximum_response_bytes:
                raise EngineeringError("external_provider_response_size")
            return payload
        except EngineeringError:
            raise
        except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
            raise EngineeringError("external_provider_unavailable") from None
        finally:
            connection.close()


@dataclass(frozen=True)
class ExternalProviderObservation:
    service: str
    operation: str
    request_digest: str
    response_payload_digest: str
    provider_observation_id: str
    provider_observed_unix_ns: int
    provider_expires_unix_ns: int
    payload: dict[str, object]
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


class ExternalReceiptClient:
    def __init__(
        self,
        endpoint: ExternalProviderEndpoint,
        *,
        transport: JsonTransport | None = None,
    ):
        if not isinstance(endpoint, ExternalProviderEndpoint):
            raise EngineeringError("external_provider_endpoint_required")
        self.endpoint = endpoint
        self.transport = HttpsJsonTransport() if transport is None else transport

    def invoke(
        self,
        operation: str,
        payload: Mapping[str, object],
        *,
        source_commit: str,
        source_tree: str,
        now_ns: int | None = None,
        request_ttl_ns: int = 30_000_000_000,
        nonce: str | None = None,
    ) -> ExternalProviderObservation:
        checked_id(operation, "external_provider_operation")
        if not isinstance(payload, Mapping):
            raise EngineeringError("external_provider_payload_required")
        if (
            not isinstance(source_commit, str)
            or len(source_commit) != 40
            or any(character not in "0123456789abcdef" for character in source_commit)
            or not isinstance(source_tree, str)
            or len(source_tree) != 40
            or any(character not in "0123456789abcdef" for character in source_tree)
        ):
            raise EngineeringError("external_provider_source_identity")
        now = time.time_ns() if now_ns is None else now_ns
        if type(now) is not int or now < 0:
            raise EngineeringError("invalid_time")
        if type(request_ttl_ns) is not int or not 1 <= request_ttl_ns <= 60_000_000_000:
            raise EngineeringError("external_provider_request_ttl")
        nonce_value = secrets.token_hex(16) if nonce is None else nonce
        checked_id(nonce_value, "external_provider_nonce")
        request_body: dict[str, object] = {
            "schema": "hepta.control-engineering-provider-request.v1",
            "service": self.endpoint.service,
            "operation": operation,
            "nonce": nonce_value,
            "sourceCommit": source_commit,
            "sourceTree": source_tree,
            "payload": dict(payload),
            "observedUnixNs": now,
            "expiresUnixNs": now + request_ttl_ns,
        }
        request_digest = semantic_digest(request_body)
        wire = dict(request_body)
        wire["requestDigest"] = request_digest
        raw_response = self.transport.post(self.endpoint, canonical_json(wire))
        try:
            decoded = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("external_provider_response_invalid") from None
        if not isinstance(decoded, dict):
            raise EngineeringError("external_provider_response_invalid")
        required = {
            "schema",
            "service",
            "operation",
            "nonce",
            "requestDigest",
            "providerObservationId",
            "providerObservedUnixNs",
            "providerExpiresUnixNs",
            "payload",
            "payloadDigest",
        }
        if set(decoded) != required:
            raise EngineeringError("external_provider_response_fields")
        if (
            decoded["schema"] != "hepta.control-engineering-provider-response.v1"
            or decoded["service"] != self.endpoint.service
            or decoded["operation"] != operation
            or decoded["nonce"] != nonce_value
            or decoded["requestDigest"] != request_digest
        ):
            raise EngineeringError("external_provider_response_binding")
        checked_id(decoded["providerObservationId"], "provider_observation_id")
        observed = decoded["providerObservedUnixNs"]
        expires = decoded["providerExpiresUnixNs"]
        if (
            type(observed) is not int
            or type(expires) is not int
            or observed > now
            or not now < expires <= now + request_ttl_ns
        ):
            raise EngineeringError("external_provider_response_window")
        response_payload = decoded["payload"]
        if not isinstance(response_payload, dict):
            raise EngineeringError("external_provider_response_payload")
        checked_sha256(decoded["payloadDigest"], "external_provider_payload_digest")
        if semantic_digest(response_payload) != decoded["payloadDigest"]:
            raise EngineeringError("external_provider_payload_digest_mismatch")
        return ExternalProviderObservation(
            self.endpoint.service,
            operation,
            request_digest,
            decoded["payloadDigest"],
            decoded["providerObservationId"],
            observed,
            expires,
            response_payload,
        )


_RECEIPT_TYPES: dict[str, type[Any]] = {
    "distributed_revocation_frontier": DistributedRevocationFrontierReceipt,
    "distributed_fence": DistributedFenceReceipt,
    "audit_anchor": AuditAnchorAttestation,
    "key_custody": KeyCustodyReceipt,
    "completion": CompletionReceipt,
    "integration_terminal": IntegrationTerminalReceipt,
}
_TUPLE_FIELDS: dict[type[Any], frozenset[str]] = {
    KeyCustodyReceipt: frozenset({"roles"}),
}


def decode_external_receipt(
    observation: ExternalProviderObservation,
    receipt_type: str,
) -> Any:
    if not isinstance(observation, ExternalProviderObservation):
        raise EngineeringError("external_provider_observation_required")
    cls = _RECEIPT_TYPES.get(receipt_type)
    if cls is None or not is_dataclass(cls):
        raise EngineeringError("external_provider_receipt_type")
    payload = observation.payload
    expected = {field.name for field in fields(cls)}
    if set(payload) != expected:
        raise EngineeringError("external_provider_receipt_fields")
    values = dict(payload)
    for name in _TUPLE_FIELDS.get(cls, frozenset()):
        value = values.get(name)
        if not isinstance(value, list):
            raise EngineeringError("external_provider_receipt_tuple")
        values[name] = tuple(value)
    try:
        return cls(**values)
    except (TypeError, ValueError):
        raise EngineeringError("external_provider_receipt_invalid") from None


@dataclass(frozen=True)
class ProductionProviderSet:
    distributed_lease: ExternalProviderEndpoint
    immutable_audit: ExternalProviderEndpoint
    key_custody: ExternalProviderEndpoint
    independent_completion: ExternalProviderEndpoint
    integration_terminal: ExternalProviderEndpoint
    deployment: ExternalProviderEndpoint
    operator_acceptance: ExternalProviderEndpoint

    def __post_init__(self) -> None:
        endpoints = (
            self.distributed_lease,
            self.immutable_audit,
            self.key_custody,
            self.independent_completion,
            self.integration_terminal,
            self.deployment,
            self.operator_acceptance,
        )
        if any(not isinstance(value, ExternalProviderEndpoint) for value in endpoints):
            raise EngineeringError("production_provider_set_invalid")
        services = tuple(value.service for value in endpoints)
        if len(set(services)) != len(services):
            raise EngineeringError("production_provider_role_collision")

    @property
    def configuration_digest(self) -> str:
        rows = []
        for endpoint in (
            self.distributed_lease,
            self.immutable_audit,
            self.key_custody,
            self.independent_completion,
            self.integration_terminal,
            self.deployment,
            self.operator_acceptance,
        ):
            rows.append(
                {
                    "service": endpoint.service,
                    "url": endpoint.url,
                    "tlsCertificateSha256": endpoint.tls_certificate_sha256,
                    "clientCertificateConfigured": bool(
                        endpoint.client_certificate_file
                    ),
                    "timeoutSeconds": endpoint.timeout_seconds,
                    "maximumResponseBytes": endpoint.maximum_response_bytes,
                }
            )
        return semantic_digest(rows)
