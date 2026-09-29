#!/usr/bin/env python3
"""Verify out-of-tree, Ed25519-signed channel.matrix qualification attestations."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
ED25519_SPKI_BYTES = 44
ED25519_SIGNATURE_BYTES = 64


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _external_regular_bytes(path: Path, budget: int, label: str) -> tuple[Path, bytes]:
    absolute = path.absolute()
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or resolved != absolute:
        raise ValueError(f"canonical regular {label} required")
    if resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f"{label} must stay outside the candidate checkout")
    before = resolved.stat()
    if before.st_size > budget:
        raise ValueError(f"{label} exceeds budget")
    payload = resolved.read_bytes()
    after = resolved.stat()
    identity = lambda row: (
        row.st_dev,
        row.st_ino,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )
    if identity(before) != identity(after) or len(payload) != before.st_size:
        raise ValueError(f"{label} changed while being read")
    return resolved, payload


def _object(payload: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} key")
            result[key] = value
        return result

    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def _sibling_name(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise ValueError(f"{label} must be a sibling file")
    return value


def _openssl(args: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["openssl", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("OpenSSL execution failed") from exc
    if result.returncode != 0:
        raise ValueError("OpenSSL rejected governed evidence")
    return result.stdout


def _ed25519_spki(public_key: bytes) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="hepta-matrix-key-") as temporary:
        key = Path(temporary) / "public.pem"
        key.write_bytes(public_key)
        der = _openssl(
            ["pkey", "-pubin", "-in", str(key), "-pubout", "-outform", "DER"]
        )
    if (
        len(der) != ED25519_SPKI_BYTES
        or not der.startswith(ED25519_SPKI_PREFIX)
    ):
        raise ValueError("governed public key must be canonical Ed25519")
    return der, _digest(der)


def load_policy(path: Path) -> dict[str, Any]:
    policy_path, policy_bytes = _external_regular_bytes(
        path, MAX_POLICY_BYTES, "governance policy"
    )
    row = _object(policy_bytes, "governance policy")
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
    public_keys = {}
    public_key_sha256 = {}
    public_key_spki_sha256 = {}
    for scope in SCOPES:
        key_path, key_bytes = _external_regular_bytes(
            policy_path.parent / _sibling_name(names[scope], "public key"),
            MAX_PUBLIC_KEY_BYTES,
            "public key",
        )
        _, spki_sha256 = _ed25519_spki(key_bytes)
        public_keys[scope] = {"path": key_path, "bytes": key_bytes}
        public_key_sha256[scope] = _digest(key_bytes)
        public_key_spki_sha256[scope] = spki_sha256
    if len(set(public_key_spki_sha256.values())) != len(SCOPES):
        raise ValueError("governed scopes require distinct Ed25519 keys")
    return {
        "path": policy_path,
        "sha256": _digest(policy_bytes),
        "namespace": namespace,
        "principals": principals,
        "public_keys": public_keys,
        "public_key_sha256": public_key_sha256,
        "public_key_spki_sha256": public_key_spki_sha256,
    }


def _safe_sibling(
    directory: Path, name: object, budget: int, label: str
) -> tuple[Path, bytes]:
    return _external_regular_bytes(
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


def _verify_signature(payload: bytes, signature: bytes, public_key: bytes) -> None:
    if len(signature) != ED25519_SIGNATURE_BYTES:
        raise ValueError("Ed25519 signature must contain exactly 64 bytes")
    with tempfile.TemporaryDirectory(prefix="hepta-matrix-attestation-") as temporary:
        root = Path(temporary)
        message = root / "message"
        signature_path = root / "signature"
        public_key_path = root / "public.pem"
        message.write_bytes(payload)
        signature_path.write_bytes(signature)
        public_key_path.write_bytes(public_key)
        _openssl(
            [
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key_path),
                "-rawin",
                "-in",
                str(message),
                "-sigfile",
                str(signature_path),
            ]
        )


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
    receipt_path, receipt_bytes = _external_regular_bytes(
        receipt, MAX_ATTESTATION_BYTES, "attestation"
    )
    signature_path, signature_bytes = _external_regular_bytes(
        signature, ED25519_SIGNATURE_BYTES, "signature"
    )
    row = _object(receipt_bytes, "governed attestation")
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
    manifest_path, manifest_bytes = _safe_sibling(
        directory, manifest.get("path"), MAX_MANIFEST_BYTES, "evidence manifest"
    )
    expected_manifest = {
        "path": manifest_path.name,
        "bytes": len(manifest_bytes),
        "sha256": _digest(manifest_bytes),
    }
    if manifest != expected_manifest:
        raise ValueError("evidence manifest identity mismatch")
    key = policy["public_keys"][scope]["bytes"]
    _verify_signature(
        _signed_payload(policy["namespace"], scope, receipt_bytes),
        signature_bytes,
        key,
    )
    return {
        "state": "passed",
        "principal": principal,
        "issued_at_unix_ms": issued,
        "checks": checks,
        "attestation": {
            "path": receipt_path.name,
            "bytes": len(receipt_bytes),
            "sha256": _digest(receipt_bytes),
        },
        "signature": {
            "path": signature_path.name,
            "bytes": len(signature_bytes),
            "sha256": _digest(signature_bytes),
        },
        "evidence_manifest": expected_manifest,
    }


def verify_attestations(
    directory: Path,
    candidate: dict[str, str],
    policy_path: Path,
) -> dict[str, Any]:
    absolute = directory.absolute()
    evidence_directory = directory.resolve(strict=True)
    if (
        directory.is_symlink()
        or not evidence_directory.is_dir()
        or evidence_directory != absolute
    ):
        raise ValueError("canonical regular governed evidence directory required")
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
            "public_key_spki_sha256": policy["public_key_spki_sha256"],
        },
        "receipts": receipts,
        "scope": "cryptographically_verified_external_receipts_not_activation_or_release",
        "authority_granted": False,
        "activation": False,
        "release": False,
    }
