#!/usr/bin/env python3
"""Validate one exact, externally signed channel.matrix production bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import channel_matrix_production_qualification as production

ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA = "hepta.channel-matrix-production-governance-policy.v1"
ATTESTATION_SCHEMA = "hepta.channel-matrix-production-governed-attestation.v1"
RESULT_SCHEMA = "hepta.channel-matrix-production-bundle-validation.v1"
TARGET_SCOPE = "target_qualification"
SECURITY_SCOPE = "security_acceptance"
OPERATIONS_SCOPE = "operations_acceptance"
SCOPES = (TARGET_SCOPE, SECURITY_SCOPE, OPERATIONS_SCOPE)
MANIFEST_NAMES = {
    TARGET_SCOPE: "target-qualification.manifest.json",
    SECURITY_SCOPE: "independent-acceptance.manifest.json",
    OPERATIONS_SCOPE: "independent-acceptance.manifest.json",
}
VALIDATION_NAMES = {
    TARGET_SCOPE: "target-qualification.validation.json",
    SECURITY_SCOPE: "independent-acceptance.validation.json",
    OPERATIONS_SCOPE: "independent-acceptance.validation.json",
}
SECURITY_CHECKS = (
    "evidence_reproduction",
    "release_boundary_review",
    "security_threat_review",
)
OPERATIONS_CHECKS = (
    "operator_runbook_review",
    "restore_rollback_drill_review",
)
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
    "promotion",
    "release",
}
ARTIFACT_FIELDS = {"path", "bytes", "sha256"}
DOMAIN = b"hepta.channel-matrix-production-governed-attestation.v1\0"
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
ED25519_SPKI_BYTES = 44
ED25519_SIGNATURE_BYTES = 64
MAX_POLICY_BYTES = 64 * 1024
MAX_PUBLIC_KEY_BYTES = 64 * 1024
MAX_ATTESTATION_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}")
IDENTIFIER = re.compile(r"[A-Za-z0-9@._:-]{1,160}")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _object(payload: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _stable_external(path: Path, maximum: int, label: str) -> tuple[Path, bytes]:
    absolute = path.absolute()
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or resolved != absolute:
        raise ValueError(f"canonical regular {label} required")
    if resolved.is_relative_to(ROOT.resolve()):
        raise ValueError(f"{label} must remain outside the candidate checkout")
    before = resolved.stat()
    if not 0 <= before.st_size <= maximum:
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


def _external_directory(path: Path) -> Path:
    absolute = path.absolute()
    resolved = path.resolve(strict=True)
    if (
        path.is_symlink()
        or not resolved.is_dir()
        or resolved != absolute
        or resolved.is_relative_to(ROOT.resolve())
    ):
        raise ValueError("canonical external production evidence directory required")
    return resolved


def _candidate(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != {"commit", "tree"}
        or any(not isinstance(item, str) or not HEX40.fullmatch(item) for item in value.values())
    ):
        raise ValueError("invalid exact candidate")
    return dict(value)


def _sibling(directory: Path, value: object, maximum: int, label: str) -> tuple[Path, bytes]:
    if (
        not isinstance(value, str)
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise ValueError(f"{label} must be one sibling file")
    return _stable_external(directory / value, maximum, label)


def _openssl(arguments: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["openssl", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("OpenSSL execution failed") from exc
    if result.returncode != 0:
        raise ValueError("OpenSSL rejected production governance evidence")
    return result.stdout


def _ed25519_spki(public_key: bytes) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="hepta-matrix-production-key-") as temporary:
        path = Path(temporary) / "public.pem"
        path.write_bytes(public_key)
        der = _openssl(
            ["pkey", "-pubin", "-in", str(path), "-pubout", "-outform", "DER"]
        )
    if len(der) != ED25519_SPKI_BYTES or not der.startswith(ED25519_SPKI_PREFIX):
        raise ValueError("production governance key must be canonical Ed25519")
    return der, _digest(der)


def _signed_payload(namespace: str, scope: str, payload: bytes) -> bytes:
    return DOMAIN + namespace.encode("ascii") + b"\0" + scope.encode("ascii") + b"\0" + payload


def _verify_signature(payload: bytes, signature: bytes, public_key: bytes) -> None:
    if len(signature) != ED25519_SIGNATURE_BYTES:
        raise ValueError("Ed25519 signature must contain exactly 64 bytes")
    with tempfile.TemporaryDirectory(prefix="hepta-matrix-production-attestation-") as temporary:
        root = Path(temporary)
        message = root / "message"
        signature_path = root / "signature"
        public_path = root / "public.pem"
        message.write_bytes(payload)
        signature_path.write_bytes(signature)
        public_path.write_bytes(public_key)
        _openssl(
            [
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_path),
                "-rawin",
                "-in",
                str(message),
                "-sigfile",
                str(signature_path),
            ]
        )


def load_policy(path: Path) -> dict[str, Any]:
    policy_path, payload = _stable_external(path, MAX_POLICY_BYTES, "production governance policy")
    row = _object(payload, "production governance policy")
    if set(row) != POLICY_FIELDS or row.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported production governance policy")
    namespace = row.get("namespace")
    if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", namespace):
        raise ValueError("invalid production governance namespace")
    principals = row.get("principals")
    names = row.get("publicKeys")
    if (
        not isinstance(principals, dict)
        or set(principals) != set(SCOPES)
        or not isinstance(names, dict)
        or set(names) != set(SCOPES)
    ):
        raise ValueError("production governance scopes are incomplete")
    if any(
        not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
        for value in principals.values()
    ) or len(set(principals.values())) != len(SCOPES):
        raise ValueError("production governance principals must be distinct")
    keys: dict[str, bytes] = {}
    raw_digests: dict[str, str] = {}
    spki_digests: dict[str, str] = {}
    for scope in SCOPES:
        key_path, key_bytes = _sibling(
            policy_path.parent, names[scope], MAX_PUBLIC_KEY_BYTES, "production public key"
        )
        _, spki = _ed25519_spki(key_bytes)
        keys[scope] = key_bytes
        raw_digests[scope] = _digest(key_bytes)
        spki_digests[scope] = spki
        if key_path.name != names[scope]:
            raise ValueError("production public key identity mismatch")
    if len(set(spki_digests.values())) != len(SCOPES):
        raise ValueError("target, security and operations require distinct Ed25519 keys")
    return {
        "path": policy_path,
        "sha256": _digest(payload),
        "namespace": namespace,
        "principals": dict(principals),
        "keys": keys,
        "publicKeySha256": raw_digests,
        "publicKeySpkiSha256": spki_digests,
    }


def _manifest_identity(path: Path, payload: bytes) -> dict[str, Any]:
    return {"path": path.name, "bytes": len(payload), "sha256": _digest(payload)}


def _validated_result(
    directory: Path,
    scope: str,
    row: dict[str, Any],
) -> tuple[Path, bytes]:
    path, payload = _stable_external(
        directory / VALIDATION_NAMES[scope],
        MAX_MANIFEST_BYTES,
        "production validation result",
    )
    expected = (json.dumps(row, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if payload != expected:
        raise ValueError("production validation result is stale or non-canonical")
    return path, payload


def _expected_checks(scope: str, profile: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    if scope == TARGET_SCOPE:
        return profile[TARGET_SCOPE]
    if scope == SECURITY_SCOPE:
        return SECURITY_CHECKS
    if scope == OPERATIONS_SCOPE:
        return OPERATIONS_CHECKS
    raise ValueError("unsupported production governance scope")


def _verify_attestation(
    directory: Path,
    scope: str,
    candidate: dict[str, str],
    expected_manifest: dict[str, Any],
    expected_checks: tuple[str, ...],
    policy: dict[str, Any],
) -> dict[str, Any]:
    stem = scope.replace("_", "-") + ".attestation.json"
    receipt_path, receipt_bytes = _stable_external(
        directory / stem, MAX_ATTESTATION_BYTES, "production attestation"
    )
    _, signature = _stable_external(
        directory / f"{stem}.sig",
        ED25519_SIGNATURE_BYTES,
        "production attestation signature",
    )
    row = _object(receipt_bytes, "production attestation")
    if set(row) != ATTESTATION_FIELDS or row.get("schema") != ATTESTATION_SCHEMA:
        raise ValueError("unsupported production attestation")
    if (
        row.get("scope") != scope
        or row.get("result") != "pass"
        or _candidate(row.get("candidate")) != candidate
        or row.get("principal") != policy["principals"][scope]
    ):
        raise ValueError("production attestation identity mismatch")
    issued = row.get("issuedAtUnixMs")
    if type(issued) is not int or not 0 < issued <= 2**63 - 1:
        raise ValueError("invalid production attestation time")
    if tuple(row.get("checks", ())) != expected_checks:
        raise ValueError("production attestation check inventory mismatch")
    if row.get("evidenceManifest") != expected_manifest:
        raise ValueError("production attestation does not bind the validated manifest")
    for denied in ("authorityGranted", "activation", "promotion", "release"):
        if row.get(denied) is not False:
            raise ValueError(f"production attestation cannot grant {denied}")
    _verify_signature(
        _signed_payload(policy["namespace"], scope, receipt_bytes),
        signature,
        policy["keys"][scope],
    )
    return {
        "principal": row["principal"],
        "issuedAtUnixMs": issued,
        "checks": list(expected_checks),
        "attestation": _manifest_identity(receipt_path, receipt_bytes),
        "signature": {
            "path": f"{stem}.sig",
            "bytes": len(signature),
            "sha256": _digest(signature),
        },
        "evidenceManifest": expected_manifest,
    }


def validate_bundle(
    directory: Path,
    policy_path: Path,
    expected_candidate: dict[str, str],
) -> dict[str, Any]:
    evidence = _external_directory(directory)
    candidate = _candidate(expected_candidate)
    profile, profile_sha256 = production.load_profile()
    independent = set(profile["independent_acceptance"])
    if (
        set(SECURITY_CHECKS).intersection(OPERATIONS_CHECKS)
        or set(SECURITY_CHECKS).union(OPERATIONS_CHECKS) != independent
    ):
        raise ValueError("independent security/operations check partition is incomplete")

    target_path, target_bytes = _stable_external(
        evidence / MANIFEST_NAMES[TARGET_SCOPE],
        MAX_MANIFEST_BYTES,
        "target qualification manifest",
    )
    acceptance_path, acceptance_bytes = _stable_external(
        evidence / MANIFEST_NAMES[SECURITY_SCOPE],
        MAX_MANIFEST_BYTES,
        "independent acceptance manifest",
    )
    target = production.validate_manifest(target_path, candidate)
    acceptance = production.validate_manifest(acceptance_path, candidate)
    if target["scope"] != TARGET_SCOPE or acceptance["scope"] != "independent_acceptance":
        raise ValueError("production manifest scope mismatch")
    if target["executor"]["principal"] == acceptance["executor"]["principal"]:
        raise ValueError("target execution and independent acceptance require distinct principals")
    if acceptance["executor"]["startedAtUnixMs"] < target["executor"]["finishedAtUnixMs"]:
        raise ValueError("independent acceptance must follow target execution")

    target_validation_path, target_validation_bytes = _validated_result(
        evidence, TARGET_SCOPE, target
    )
    acceptance_validation_path, acceptance_validation_bytes = _validated_result(
        evidence, SECURITY_SCOPE, acceptance
    )
    policy = load_policy(policy_path)
    manifest_identities = {
        TARGET_SCOPE: _manifest_identity(
            target_validation_path, target_validation_bytes
        ),
        SECURITY_SCOPE: _manifest_identity(
            acceptance_validation_path, acceptance_validation_bytes
        ),
        OPERATIONS_SCOPE: _manifest_identity(
            acceptance_validation_path, acceptance_validation_bytes
        ),
    }
    attestations = {
        scope: _verify_attestation(
            evidence,
            scope,
            candidate,
            manifest_identities[scope],
            _expected_checks(scope, profile),
            policy,
        )
        for scope in SCOPES
    }
    if (
        attestations[SECURITY_SCOPE]["issuedAtUnixMs"]
        < attestations[TARGET_SCOPE]["issuedAtUnixMs"]
        or attestations[OPERATIONS_SCOPE]["issuedAtUnixMs"]
        < attestations[TARGET_SCOPE]["issuedAtUnixMs"]
    ):
        raise ValueError("independent attestations must follow target attestation")

    return {
        "schema": RESULT_SCHEMA,
        "candidate": candidate,
        "result": "pass",
        "productionQualified": True,
        "targetQualification": target,
        "independentAcceptance": acceptance,
        "attestations": attestations,
        "governancePolicy": {
            "path": policy["path"].name,
            "sha256": policy["sha256"],
            "namespace": policy["namespace"],
            "publicKeySha256": policy["publicKeySha256"],
            "publicKeySpkiSha256": policy["publicKeySpkiSha256"],
        },
        "productionProfileSha256": profile_sha256,
        "authorityGranted": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--governance-policy", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        row = validate_bundle(
            args.directory,
            args.governance_policy,
            {"commit": args.expected_commit, "tree": args.expected_tree},
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failure = {
            "schema": RESULT_SCHEMA,
            "result": "fail",
            "error": str(exc),
            "productionQualified": False,
            "authorityGranted": False,
            "activation": False,
            "promotion": False,
            "release": False,
        }
        print(json.dumps(failure, sort_keys=True))
        return 2
    encoded = json.dumps(row, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output.absolute()
        if output.is_relative_to(ROOT.resolve()):
            raise SystemExit("output must remain outside the candidate checkout")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
