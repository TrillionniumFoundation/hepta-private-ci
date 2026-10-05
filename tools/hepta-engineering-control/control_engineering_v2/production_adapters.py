"""Fail-closed adapters for externally governed production evidence.

The repository cannot manufacture distributed consensus, immutable audit storage,
HSM/KMS custody, deployment observation or operator acceptance. It can define a
bounded HTTPS transport, verify role-separated externally signed receipts and emit
one evidence decision whose authority fields remain false.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
from typing import Mapping
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from .clock_policy import ClockPolicy, validate_signed_window
from .control_plane import EngineeringError, canonical_json, checked_sha256, semantic_digest
from .evidence import HmacTrustStore, SignatureTrustStore

EXTERNAL_RECEIPT_SCHEMA = "hepta.control-engineering-external-receipt.v1"
MAX_EXTERNAL_RECEIPT_BYTES = 1_048_576
REQUIRED_EXTERNAL_ROLES = (
    "distributed_lease_fence",
    "immutable_audit_anchor",
    "key_custody:source_authority",
    "key_custody:ci_executor",
    "key_custody:independent_evaluator",
    "key_custody:integration_terminal_observer",
    "independent_ci_completion",
    "integration_terminal_observer",
    "target_deployment_observer",
    "backup_restore_rehearsal_observer",
    "rollback_rehearsal_observer",
    "operator_acceptance",
)


@dataclass(frozen=True)
class ExternalProductionReceipt:
    role: str
    provider: str
    provider_instance: str
    issuer: str
    signing_identity: str
    source_commit: str
    source_tree: str
    target_digest: str
    evidence_digest: str
    evidence_class: str
    observed_unix_ns: int
    expires_unix_ns: int
    nonce: str
    signature: str = ""
    schema: str = EXTERNAL_RECEIPT_SCHEMA


@dataclass(frozen=True)
class PublicKeyBinding:
    public_key_path: str
    algorithm: str


@dataclass(frozen=True)
class ProductionEvidenceDecision:
    source_commit: str
    source_tree: str
    target_digest: str
    verified_roles: tuple[str, ...]
    evidence_digest: str
    production_evidence_complete: bool
    deployment_observed: bool
    backup_restore_rehearsed: bool
    rollback_rehearsed: bool
    operator_accepted: bool
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False
    external_effect_authority: bool = False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise EngineeringError("external_provider_redirect_rejected")


class HttpsJsonReceiptProvider:
    def __init__(
        self,
        endpoint: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: int = 15,
        authorization_env: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        maximum_response_bytes: int = MAX_EXTERNAL_RECEIPT_BYTES,
    ):
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise EngineeringError("external_provider_endpoint")
        if parsed.hostname not in allowed_hosts:
            raise EngineeringError("external_provider_host")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise EngineeringError("external_provider_timeout")
        if (
            type(maximum_response_bytes) is not int
            or not 1 <= maximum_response_bytes <= MAX_EXTERNAL_RECEIPT_BYTES
        ):
            raise EngineeringError("external_provider_response_limit")
        if authorization_env is not None and (
            not isinstance(authorization_env, str) or not authorization_env
        ):
            raise EngineeringError("external_provider_authorization")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.authorization_env = authorization_env
        self.maximum_response_bytes = maximum_response_bytes
        context = ssl.create_default_context() if ssl_context is None else ssl_context
        self._opener = build_opener(_NoRedirect(), HTTPSHandler(context=context))

    @staticmethod
    def _unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EngineeringError("external_provider_duplicate_json_key")
            result[key] = value
        return result

    def fetch(self, request_body: Mapping[str, object]) -> ExternalProductionReceipt:
        if not isinstance(request_body, Mapping):
            raise EngineeringError("external_provider_request")
        payload = canonical_json(dict(request_body))
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "hepta-control-engineering/1",
        }
        if self.authorization_env is not None:
            token = os.environ.get(self.authorization_env)
            if not token or "\n" in token or "\r" in token:
                raise EngineeringError("external_provider_authorization")
            headers["Authorization"] = "Bearer " + token
        request = Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                raw = response.read(self.maximum_response_bytes + 1)
        except EngineeringError:
            raise
        except Exception as error:
            raise EngineeringError("external_provider_unavailable") from error
        if content_type != "application/json" or len(raw) > self.maximum_response_bytes:
            raise EngineeringError("external_provider_response")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=self._unique_pairs)
            return ExternalProductionReceipt(**value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise EngineeringError("external_provider_response") from None


class OpenSslPublicKeyTrustStore:
    """Read-only PEM public-key verifier; this implementation never signs."""

    def __init__(self, bindings: Mapping[tuple[str, str], PublicKeyBinding]):
        self._bindings = dict(bindings)
        for binding in self._bindings.values():
            if not isinstance(binding, PublicKeyBinding):
                raise EngineeringError("public_key_binding")
            path = Path(binding.public_key_path)
            if not path.is_file() or path.is_symlink():
                raise EngineeringError("public_key_path")
            if binding.algorithm not in {
                "ed25519",
                "rsa-pss-sha256",
                "ecdsa-sha256",
            }:
                raise EngineeringError("public_key_algorithm")

    def sign(self, value: object, issuer: str, signing_identity: str) -> str:
        raise RuntimeError("external_private_key_unavailable")

    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool:
        binding = self._bindings.get((issuer, signing_identity))
        if binding is None or not isinstance(signature, str):
            return False
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except (ValueError, TypeError):
            return False
        if not signature_bytes or len(signature_bytes) > 16_384:
            return False
        payload = HmacTrustStore.payload(value)
        with tempfile.TemporaryDirectory(prefix="hepta-external-signature-") as temp:
            root = Path(temp)
            payload_path = root / "payload"
            signature_path = root / "signature"
            payload_path.write_bytes(payload)
            signature_path.write_bytes(signature_bytes)
            if binding.algorithm == "ed25519":
                command = [
                    "/usr/bin/openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    binding.public_key_path,
                    "-rawin",
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(signature_path),
                ]
            else:
                command = [
                    "/usr/bin/openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    binding.public_key_path,
                    "-signature",
                    str(signature_path),
                ]
                if binding.algorithm == "rsa-pss-sha256":
                    command.extend(
                        [
                            "-sigopt",
                            "rsa_padding_mode:pss",
                            "-sigopt",
                            "rsa_pss_saltlen:-1",
                        ]
                    )
                command.append(str(payload_path))
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            return result.returncode == 0


def _sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
        or value == "0" * 40
    ):
        raise EngineeringError(label)
    return value


def verify_external_production_bundle(
    receipts: Mapping[str, ExternalProductionReceipt],
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    expected_target_digest: str,
    now_ns: int,
    clock_policy: ClockPolicy = ClockPolicy(),
) -> ProductionEvidenceDecision:
    _sha1(expected_source_commit, "external_source_commit")
    _sha1(expected_source_tree, "external_source_tree")
    checked_sha256(expected_target_digest, "external_target_digest")
    if not isinstance(receipts, Mapping) or set(receipts) != set(REQUIRED_EXTERNAL_ROLES):
        raise EngineeringError("external_evidence_role_set")
    seen_identities: set[tuple[str, str]] = set()
    verified: list[dict[str, object]] = []
    for role in REQUIRED_EXTERNAL_ROLES:
        receipt = receipts[role]
        if not isinstance(receipt, ExternalProductionReceipt):
            raise EngineeringError("external_evidence_receipt")
        if (
            receipt.schema != EXTERNAL_RECEIPT_SCHEMA
            or receipt.role != role
            or receipt.source_commit != expected_source_commit
            or receipt.source_tree != expected_source_tree
            or receipt.target_digest != expected_target_digest
            or receipt.evidence_class != "external_observation"
        ):
            raise EngineeringError("external_evidence_binding")
        for value, label in (
            (receipt.provider, "external_provider"),
            (receipt.provider_instance, "external_provider_instance"),
            (receipt.issuer, "external_issuer"),
            (receipt.signing_identity, "external_signing_identity"),
            (receipt.nonce, "external_nonce"),
        ):
            if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
                raise EngineeringError(label)
        folded = " ".join(
            (receipt.provider, receipt.provider_instance, receipt.evidence_class)
        ).casefold()
        if any(marker in folded for marker in ("fixture", "reference", "test-only", "mock")):
            raise EngineeringError("external_evidence_fixture")
        checked_sha256(receipt.evidence_digest, "external_evidence_digest")
        validate_signed_window(
            receipt.observed_unix_ns,
            receipt.expires_unix_ns,
            now_ns=now_ns,
            policy=clock_policy,
            label="external_evidence",
        )
        identity = (receipt.provider_instance, receipt.signing_identity)
        if identity in seen_identities:
            raise EngineeringError("external_evidence_role_collision")
        seen_identities.add(identity)
        if not trust_store.verify(
            receipt,
            receipt.issuer,
            receipt.signing_identity,
            receipt.signature,
        ):
            raise EngineeringError("external_evidence_signature")
        verified.append(
            {
                "role": role,
                "provider": receipt.provider,
                "providerInstance": receipt.provider_instance,
                "signingIdentity": receipt.signing_identity,
                "receiptDigest": semantic_digest(asdict(receipt)),
            }
        )
    evidence_digest = semantic_digest(
        {
            "sourceCommit": expected_source_commit,
            "sourceTree": expected_source_tree,
            "targetDigest": expected_target_digest,
            "verified": verified,
        }
    )
    return ProductionEvidenceDecision(
        expected_source_commit,
        expected_source_tree,
        expected_target_digest,
        tuple(REQUIRED_EXTERNAL_ROLES),
        evidence_digest,
        True,
        True,
        True,
        True,
        True,
    )


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EngineeringError("external_evidence_duplicate_json_key")
        result[key] = value
    return result


def load_external_receipts(path: str | Path) -> dict[str, ExternalProductionReceipt]:
    receipt_path = Path(path)
    try:
        if not receipt_path.is_file() or receipt_path.is_symlink():
            raise EngineeringError("external_evidence_file")
        raw = receipt_path.read_bytes()
    except EngineeringError:
        raise
    except OSError as error:
        raise EngineeringError("external_evidence_file") from error
    if not raw or len(raw) > MAX_EXTERNAL_RECEIPT_BYTES:
        raise EngineeringError("external_evidence_file")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_pairs,
        )
    except EngineeringError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError("external_evidence_file") from None
    if not isinstance(value, dict):
        raise EngineeringError("external_evidence_file")
    try:
        return {
            role: ExternalProductionReceipt(**receipt)
            for role, receipt in value.items()
        }
    except (TypeError, AttributeError):
        raise EngineeringError("external_evidence_file") from None
