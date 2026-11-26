#!/usr/bin/env python3
"""A0: fail-closed, signed on-host deployment evidence census (no promotion).

This tool NEVER obtains proof of deployment by reading source fixtures or by
counting digests. It checks a signed active Cell registry, per-Cell signed
evidence, and actual manifest/weight/checkpoint bytes under --evidence-root.
The public key must be independently provisioned by the operator.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

SCHEMA_REGISTRY = "hepta.neuron.deployment-registry.a0.v1"
SCHEMA_CELL = "hepta.neuron.deployed-cell-evidence.a0.v1"
SCHEMA_MANIFEST = "hepta.neuron.selected-model.a0.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CELL_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ALLOWED_MECHANISMS = {"sparse-v1", "population-v2", "gated-sparse-v3"}


class EvidenceError(ValueError):
    pass


def need(value: bool, reason: str) -> None:
    if not value:
        raise EvidenceError(reason)


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def object_json(data: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise EvidenceError(f"{label}: non-finite JSON value {value}")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            need(key not in result, f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data, parse_constant=reject_constant, object_pairs_hook=unique_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label}: invalid JSON") from exc
    need(isinstance(value, dict), f"{label}: expected JSON object")
    return value


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    need(set(value) == expected, f"{label}: missing or unexpected fields")


_DIGEST_CACHE: dict[tuple[str, int, int, int, int, int], tuple[str, int]] = {}


def sha_file(path: Path) -> tuple[str, int]:
    # Shared Encoder blobs can back thousands of Cells. Rehash a stable inode
    # once, never once per Cell; this still requires an immutable owner snapshot.
    before = path.stat()
    key = (str(path), before.st_dev, before.st_ino, before.st_size,
           before.st_mtime_ns, before.st_ctime_ns)
    if key in _DIGEST_CACHE:
        return _DIGEST_CACHE[key]
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            count += len(block)
    after = path.stat()
    need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
          before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                 after.st_mtime_ns, after.st_ctime_ns),
         "artifact changed while being hashed")
    result = digest.hexdigest(), count
    _DIGEST_CACHE[key] = result
    return result


def hex_digest(value: Any, label: str) -> None:
    need(isinstance(value, str) and HEX64.fullmatch(value) is not None, f"{label}: invalid sha256")
    need(value != "0" * 64, f"{label}: zero sha256 forbidden")


def positive_int(value: Any, label: str, *, allow_zero: bool = False) -> None:
    need(
        type(value) is int and (value >= 0 if allow_zero else value > 0),
        f"{label}: expected {'nonnegative' if allow_zero else 'positive'} integer",
    )


def local_path(root: Path, relative: Any, label: str) -> Path:
    need(isinstance(relative, str) and relative != "", f"{label}: missing path")
    untrusted = Path(relative)
    need(not untrusted.is_absolute(), f"{label}: absolute path rejected")
    need(all(part not in (".", "..") for part in untrusted.parts),
         f"{label}: traversal components rejected")
    # The trusted owner must mount a frozen read-only snapshot: the checks below
    # reject ordinary symlinks but cannot defeat a malicious concurrent rename.
    candidate = root
    for part in untrusted.parts:
        candidate /= part
        need(not candidate.is_symlink(), f"{label}: symlinks are not evidence")
    resolved = candidate.resolve(strict=True)
    need(resolved.is_relative_to(root) and resolved.is_file(),
         f"{label}: path leaves evidence root")
    return resolved


def check_blob(root: Path, path: Any, digest: Any, label: str, size: Any = None) -> int:
    hex_digest(digest, label)
    real = local_path(root, path, label)
    observed_hash, observed_bytes = sha_file(real)
    need(observed_hash == digest, f"{label}: bytes do not match sha256")
    need(observed_bytes > 0, f"{label}: empty physical artifact")
    if size is not None:
        positive_int(size, f"{label}.size")
        need(observed_bytes == size, f"{label}: size mismatch")
    return observed_bytes


def load_public_key(path: Path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise EvidenceError("cryptography is required to verify Ed25519 signatures") from exc
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except (ValueError, OSError) as exc:
        raise EvidenceError("unable to load trusted PEM key") from exc
    need(isinstance(key, Ed25519PublicKey), "trusted signer must be Ed25519")
    fingerprint = hashlib.sha256(
        key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).hexdigest()
    return key, fingerprint


def verify_signed(path: Path, pubkey: Any, fingerprint: str, expected_schema: str) -> dict[str, Any]:
    envelope = object_json(path.read_bytes(), str(path))
    exact_keys(envelope, {"payload", "signature_b64", "signer_key_id"}, str(path))
    payload = envelope["payload"]
    need(isinstance(payload, dict), f"{path}: missing payload")
    need(payload.get("schema") == expected_schema, f"{path}: incorrect schema")
    need(envelope["signer_key_id"] == fingerprint, f"{path}: wrong trusted signer")
    try:
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise EvidenceError(f"{path}: invalid signature encoding") from exc
    need(len(signature) == 64, f"{path}: invalid Ed25519 signature length")
    try:
        pubkey.verify(signature, canonical(payload))
    except Exception as exc:
        raise EvidenceError(f"{path}: invalid signature") from exc
    return payload


def evaluate(
    root: Path,
    trusted_key: Path,
    *,
    expected_host_id: str | None = None,
    max_age_seconds: int | None = None,
    evaluation_asof_utc: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    need(root.is_dir(), "evidence root must be a directory")
    pubkey, fingerprint = load_public_key(trusted_key)
    registry = verify_signed(root / "registry.json", pubkey, fingerprint, SCHEMA_REGISTRY)
    exact_keys(registry, {"schema", "host_id", "observed_at_utc", "active_cells"}, "registry")
    host = registry["host_id"]
    need(isinstance(host, str) and host.strip() != "", "registry missing host identity")
    if expected_host_id is not None:
        need(isinstance(expected_host_id, str) and expected_host_id.strip() != "",
             "operator expected host ID is invalid")
        need(host == expected_host_id, "registry does not match independently expected host")
    observed = registry["observed_at_utc"]
    need(isinstance(observed, str) and observed.endswith("Z"),
         "registry missing UTC observation time")
    try:
        observed_time = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("registry UTC observation time is invalid") from exc
    if max_age_seconds is not None:
        need(type(max_age_seconds) is int and 1 <= max_age_seconds <= 86_400,
             "maximum snapshot age must be between 1 and 86400 seconds")
        asof = evaluation_asof_utc or datetime.now(timezone.utc)
        need(asof.tzinfo is not None and asof.utcoffset() == timedelta(0),
             "evaluation as-of must have UTC timezone")
        need(observed_time <= asof + timedelta(seconds=60),
             "deployment evidence is dated unacceptably into the future")
        need(observed_time >= asof - timedelta(seconds=max_age_seconds),
             "deployment evidence is stale; obtain a fresh owner snapshot")
    active = registry["active_cells"]
    need(isinstance(active, list) and bool(active) and len(active) <= 65_536,
         "registry must name at least one deployed Cell")
    seen = set()
    rows = []
    for item in active:
        need(isinstance(item, dict), "registry Cell entry not an object")
        exact_keys(item, {"cell_id", "generation", "mechanism"}, "registry Cell")
        cell_id, generation, mechanism = item["cell_id"], item["generation"], item["mechanism"]
        need(isinstance(cell_id, str) and CELL_ID.fullmatch(cell_id) is not None
             and cell_id not in (".", ".."),
             "invalid Cell identifier")
        need(cell_id not in seen, "duplicate deployed Cell")
        seen.add(cell_id)
        positive_int(generation, "registry generation")
        need(mechanism in ALLOWED_MECHANISMS, "unknown deployed mechanism")
        evidence_path = local_path(root, f"cells/{cell_id}.json", "signed Cell evidence")
        cell = verify_signed(evidence_path, pubkey, fingerprint, SCHEMA_CELL)
        exact_keys(cell, {
            "schema", "host_id", "observed_at_utc", "cell_id", "generation", "mechanism",
            "model_digest", "manifest_path", "manifest_sha256", "weights_path",
            "weights_sha256", "weights_bytes", "parameter_count", "checkpoint_path",
            "checkpoint_sha256", "checkpoint_sequence", "reopen_checkpoint_digest",
            "resource_receipt",
        }, "Cell evidence")
        for field in ("host_id", "observed_at_utc", "cell_id", "generation", "mechanism"):
            need(cell[field] == (item.get(field) if field in item else registry[field]),
                 f"Cell evidence: registry mismatch in {field}")
        hex_digest(cell["model_digest"], "model digest")
        hex_digest(cell["reopen_checkpoint_digest"], "reopen checkpoint digest")
        positive_int(cell["parameter_count"], "parameter_count")
        positive_int(cell["weights_bytes"], "weights_bytes")
        positive_int(cell["checkpoint_sequence"], "checkpoint_sequence")
        check_blob(root, cell["manifest_path"], cell["manifest_sha256"], "manifest")
        check_blob(root, cell["weights_path"], cell["weights_sha256"], "weights",
                   cell["weights_bytes"])
        check_blob(root, cell["checkpoint_path"], cell["checkpoint_sha256"], "checkpoint")
        manifest = object_json(local_path(root, cell["manifest_path"], "manifest").read_bytes(),
                               "manifest")
        exact_keys(manifest, {
            "schema", "model_digest", "mechanism", "generation", "weights_sha256",
            "weights_bytes", "parameter_count",
        }, "model manifest")
        need(manifest["schema"] == SCHEMA_MANIFEST, "selected model manifest schema mismatch")
        for field in ("model_digest", "mechanism", "generation", "weights_sha256",
                      "weights_bytes", "parameter_count"):
            need(manifest[field] == cell[field], f"manifest conflicts with {field}")
        resource = cell["resource_receipt"]
        need(isinstance(resource, dict), "resource receipt must be an object")
        exact_keys(resource, {
            "measurement_kind", "host_profile_digest", "cpu_micros", "peak_rss_bytes",
            "p95_micros", "p99_micros", "sample_count", "replay_verified",
        }, "resource receipt")
        need(resource["measurement_kind"] == "target-host-observed",
             "fixtures, projections and synthetic resources cannot establish A0")
        hex_digest(resource["host_profile_digest"], "host profile")
        for field in ("cpu_micros", "peak_rss_bytes", "p95_micros", "p99_micros", "sample_count"):
            positive_int(resource[field], field)
        need(resource["p99_micros"] >= resource["p95_micros"],
             "p99 cannot be below p95")
        need(resource["replay_verified"] is True,
             "missing explicit host replay attestation")
        rows.append({
            "cell_id": cell_id, "generation": generation, "mechanism": mechanism,
            "model_digest": cell["model_digest"],
            "weights_bytes": cell["weights_bytes"],
            "parameter_count": cell["parameter_count"],
            "checkpoint_sequence": cell["checkpoint_sequence"],
            "reopen_checkpoint_digest": cell["reopen_checkpoint_digest"],
            "cpu_micros": resource["cpu_micros"],
            "peak_rss_bytes": resource["peak_rss_bytes"],
            "p95_micros": resource["p95_micros"],
            "p99_micros": resource["p99_micros"],
            "host_profile_digest": resource["host_profile_digest"],
        })
    listed = {p.name for p in (root / "cells").glob("*.json")}
    need(listed == {f"{cell_id}.json" for cell_id in seen},
         "signed registry and Cell evidence census differ")
    return {
        "schema": "hepta.neuron.a0-audit-result.v1",
        "status": "signed-evidence-format-verified",
        "production_qualification": False,
        "host_id": host,
        "observed_at_utc": observed,
        "trusted_key_fingerprint": fingerprint,
        "registry_sha256": sha_file(root / "registry.json")[0],
        "cell_count": len(rows),
        "cells": sorted(rows, key=lambda row: row["cell_id"]),
        "limitations": [
            "Verification establishes signed file consistency, not physical host execution.",
            "Production authenticity requires externally governed signer provisioning and owner logs.",
            "A0 does not prove A1-A4 future-window NDU uplift or enable routing.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--trusted-public-key", type=Path, required=True)
    parser.add_argument("--expected-host-id", required=True)
    parser.add_argument("--max-age-seconds", type=int, default=300)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(
            args.evidence_root,
            args.trusted_public_key,
            expected_host_id=args.expected_host_id,
            max_age_seconds=args.max_age_seconds,
        )
    except (EvidenceError, FileNotFoundError, PermissionError) as exc:
        print(json.dumps({"status": "BLOCKED_A0", "error": str(exc)}), file=sys.stderr)
        return 2
    formatted = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.write_text(formatted, encoding="utf-8")
    else:
        print(formatted, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
