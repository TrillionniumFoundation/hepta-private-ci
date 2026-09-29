#!/usr/bin/env python3
"""Verify out-of-tree, Ed25519-signed channel.matrix qualification attestations."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from channel_matrix_evidence import file_digest, read_object

ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA = "hepta.channel-matrix-governance-policy.v1"
ATTESTATION_SCHEMA = "hepta.channel-matrix-governed-attestation.v1"
SCOPES = ("target_qualification", "independent_acceptance")
MAX_POLICY_BYTES = 64 * 1024
MAX_PUBLIC_KEY_BYTES = 64 * 1024
MAX_ATTESTATION_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
POLICY_FIELDS = {"schema", "namespace", "principals", "publicKeys"}
ATTESTATION_FIELDS = {
    "schema",
    "scope",
    "candidate",
    "result",
    "principal",
    "issuedAtUnixMs",
    "evidenceManifest",
    "checks",
    "authorityGranted",
    "activation",
    "release",
}
DOMAIN = b"hepta.channel-matrix-governed-attestation.v1\0"


def _external_regular(path: Path, budget: int, label: str) -> Path:
    absolute = path.absolute()
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or resolved != absolute:
        raise ValueError(f"canonical regular {label} required")
    if resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f"{label} must stay outside the candidate checkout")
    if resolved.stat().st_size > budget:
        raise ValueError(f"{label} exceeds budget")
    return resolved


def _sibling_name(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise ValueError(f"{label} must be a sibling file")
    return value


def load_policy(path: Path) -> dict[str, Any]:
    policy_path = _external_regular(path, MAX_POLICY_BYTES, "governance policy")
    row = read_object(policy_path)
    if set(row) != POLICY_FIELDS or row.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported governance policy")
    namespace = row.get("namespace")
    if (
        not isinstance(namespace, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", namespace)
    ):
        raise ValueError("invalid signature namespace")
    principals = row.get("principals")
    if (
        not isinstance(principals, dict)
        or set(principals) != set(SCOPES)
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9@._-]{1,128}", value)
            for value in principals.values()
        )
        or len(set(principals.values())) != len(SCOPES)
    ):
        raise ValueError("invalid governance principals")
    names = row.get("publicKeys")
    if not isinstance(names, dict) or set(names) != set(SCOPES):
        raise ValueError("invalid governance public keys")
    public_keys = {
        scope: _external_regular(
            policy_path.parent / _sibling_name(names[scope], "public key"),
            MAX_PUBLIC_KEY_BYTES,
            "public key",
        )
        for scope in SCOPES
    }
    if len({file_digest(path) for path in public_keys.values()}) != len(SCOPES):
        raise ValueError("governed scopes require distinct signing keys")
    return {
        "path": policy_path,
        "sha256": file_digest(policy_path),
        "namespace": namespace,
        "principals": principals,
        "public_keys": public_keys,
        "public_key_sha256": {
            scope: file_digest(key) for scope, key in public_keys.items()
        },
    }


def _safe_sibling(directory: Path, name: object, budget: int, label: str) -> Path:
    return _external_regular(
        directory / _sibling_name(name, label), budget, label
    )


def _signed_payload(namespace: str, scope: str, payload: bytes) -> bytes:
    return (
        DOMAIN
        + namespace.encode("ascii")
        + b"\0"
        + scope.encode("ascii")
        + b"\0"
        + payload
    )


def _verify_signature(
    payload: bytes,
    signature: Path,
    public_key: Path,
) -> None:
    with tempfile.NamedTemporaryFile(prefix="hepta-matrix-attestation-", delete=True) as stream:
        stream.write(payload)
        stream.flush()
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                stream.name,
                "-sigfile",
                str(signature),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    if result.returncode != 0:
        raise ValueError("attestation signature verification failed")


def verify_scope(
    directory: Path,
    scope: str,
    candidate: dict[str, str],
    policy: dict[str, Any],
) -> dict[str, Any] | None:
    if scope not in SCOPES:
        raise ValueError("unsupported governed scope")
    stem = scope.replace("_", "-") + ".attestation.json"
    receipt = directory / stem
    signature = directory / f"{stem}.sig"
    if not receipt.exists() and not signature.exists():
        return None
    receipt_path = _external_regular(receipt, MAX_ATTESTATION_BYTES, "attestation")
    signature_path = _external_regular(signature, MAX_ATTESTATION_BYTES, "signature")
    row = read_object(receipt_path)
    if set(row) != ATTESTATION_FIELDS or row.get("schema") != ATTESTATION_SCHEMA:
        raise ValueError("unsupported governed attestation")
    if row.get("scope") != scope or row.get("result") != "pass":
        raise ValueError("attestation scope or result mismatch")
    if row.get("candidate") != candidate:
        raise ValueError("attestation candidate mismatch")
    principal = policy["principals"][scope]
    if row.get("principal") != principal:
        raise ValueError("attestation principal mismatch")
    issued = row.get("issuedAtUnixMs")
    if type(issued) is not int or not 0 < issued <= 2**63 - 1:
        raise ValueError("invalid attestation time")
    checks = row.get("checks")
    if (
        not isinstance(checks, list)
        or not checks
        or len(checks) > 256
        or len(checks) != len(set(checks))
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value)
            for value in checks
        )
    ):
        raise ValueError("invalid attestation checks")
    if (
        row.get("authorityGranted") is not False
        or row.get("activation") is not False
        or row.get("release") is not False
    ):
        raise ValueError("attestation cannot grant authority, activation or release")
    manifest = row.get("evidenceManifest")
    if not isinstance(manifest, dict) or set(manifest) != {"path", "bytes", "sha256"}:
        raise ValueError("invalid evidence manifest reference")
    manifest_path = _safe_sibling(
        directory, manifest.get("path"), MAX_MANIFEST_BYTES, "evidence manifest"
    )
    expected_manifest = {
        "path": manifest_path.name,
        "bytes": manifest_path.stat().st_size,
        "sha256": file_digest(manifest_path),
    }
    if manifest != expected_manifest:
        raise ValueError("evidence manifest identity mismatch")
    payload = receipt_path.read_bytes()
    _verify_signature(
        _signed_payload(policy["namespace"], scope, payload),
        signature_path,
        policy["public_keys"][scope],
    )
    return {
        "state": "passed",
        "principal": principal,
        "issued_at_unix_ms": issued,
        "checks": checks,
        "attestation": {
            "path": receipt_path.name,
            "bytes": receipt_path.stat().st_size,
            "sha256": file_digest(receipt_path),
        },
        "signature": {
            "path": signature_path.name,
            "bytes": signature_path.stat().st_size,
            "sha256": file_digest(signature_path),
        },
        "evidence_manifest": expected_manifest,
    }


def verify_attestations(
    directory: Path,
    candidate: dict[str, str],
    policy_path: Path,
) -> dict[str, Any]:
    evidence_directory = directory.resolve(strict=True)
    if evidence_directory.is_relative_to(ROOT.resolve()):
        raise ValueError("governed evidence must stay outside the candidate checkout")
    if set(candidate) != {"commit", "tree"} or any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)
        for value in candidate.values()
    ):
        raise ValueError("invalid exact candidate")
    policy = load_policy(policy_path)
    receipts = {
        scope: verify_scope(evidence_directory, scope, candidate, policy)
        for scope in SCOPES
    }
    if (
        receipts["independent_acceptance"] is not None
        and receipts["target_qualification"] is None
    ):
        raise ValueError("independent acceptance requires target qualification")
    return {
        "policy": {
            "path": policy["path"].name,
            "sha256": policy["sha256"],
            "namespace": policy["namespace"],
            "public_key_sha256": policy["public_key_sha256"],
        },
        "receipts": receipts,
        "scope": "cryptographically_verified_external_receipts_not_activation_or_release",
        "authority_granted": False,
        "activation": False,
        "release": False,
    }
