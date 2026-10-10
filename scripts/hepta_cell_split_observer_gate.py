#!/usr/bin/env python3
"""Verify a pinned independent observer signature over an exact CellSplit matrix.

This is a *read-only authentication check*, not host attestation, independent
measurement, NDU selection, split activation, or deployment authorization.
The observer must be operated outside the candidate/measurement producer's
trust domain and retain the underlying raw evidence on the target host.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hepta_cell_split_perf_gate import (
    MODES,
    SCOPES,
    TRACE_FIELD,
    InvalidEvidence,
    analyze,
)

OBSERVER_SCHEMA = "hepta.cell-split.independent-observer.v1"
SIGNED_SCHEMA = "hepta.cell-split.signed-independent-observer.v1"
SIGNING_DOMAIN = b"hepta.cell-split.independent-observer.v1\0"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_INPUT_BYTES = 4 * 1024 * 1024


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise InvalidEvidence(f"{label}: expected a SHA-256 digest")


def read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise InvalidEvidence(f"{path.name}: evidence exceeds bounded input size")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_signature(
    payload: bytes, encoded_signature: Any, public_key: Path, pinned_key_sha256: str
) -> None:
    require_digest(pinned_key_sha256, "externally pinned observer key")
    key_bytes = public_key.read_bytes()
    if len(key_bytes) > 4096 or hashlib.sha256(key_bytes).hexdigest() != pinned_key_sha256:
        raise InvalidEvidence("observer public key differs from external trust pin")
    if b"-----BEGIN PUBLIC KEY-----" not in key_bytes:
        raise InvalidEvidence("observer key must be a public-key PEM")
    if not isinstance(encoded_signature, str):
        raise InvalidEvidence("observer signature must be base64")
    try:
        signature = base64.b64decode(encoded_signature, validate=True)
    except (ValueError, binascii.Error) as error:
        raise InvalidEvidence("malformed observer signature") from error
    if len(signature) != 64:
        raise InvalidEvidence("observer Ed25519 signature must have 64 bytes")
    # An Ed25519 algorithm check is independent of the signature format: never
    # permit an RSA/ECDSA trust anchor to silently change this wire contract.
    try:
        algorithm = subprocess.run(
            ["openssl", "pkey", "-pubin", "-in", str(public_key), "-text", "-noout"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if algorithm.returncode != 0 or b"ED25519" not in algorithm.stdout.upper():
            raise InvalidEvidence("observer public key is not Ed25519")
        with tempfile.TemporaryDirectory(prefix="hepta-observer-verify-") as folder:
            message = Path(folder) / "message"
            signature_path = Path(folder) / "signature"
            message.write_bytes(payload)
            signature_path.write_bytes(signature)
            result = subprocess.run(
                [
                    "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key),
                    "-rawin", "-in", str(message), "-sigfile", str(signature_path),
                ],
                capture_output=True,
                check=False,
                timeout=10,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InvalidEvidence("independent observer verification backend unavailable") from error
    if result.returncode != 0:
        raise InvalidEvidence("independent observer signature verification failed")


def verify_observer_packet(
    matrix: dict[str, Any],
    comparison: dict[str, Any],
    signed: dict[str, Any],
    public_key: Path,
    pinned_key_sha256: str,
) -> dict[str, Any]:
    # Recompute from the raw matrix. A signed 'pass' boolean is not a
    # measurement, and a manually altered diagnostic cannot override this.
    computed = analyze(matrix)
    if comparison != computed:
        raise InvalidEvidence("comparison does not match the exact measured matrix")
    if not isinstance(signed, dict) or signed.get("schema") != SIGNED_SCHEMA:
        raise InvalidEvidence("unsupported signed observer envelope")
    claim = signed.get("attestation")
    if not isinstance(claim, dict) or claim.get("schema") != OBSERVER_SCHEMA:
        raise InvalidEvidence("unsupported observer attestation")
    expected_keys = {
        "schema", "observer_id", "producer_id", "source_sha", "hardware_id",
        "model_digest", "workload_digest", TRACE_FIELD, "matrix_sha256",
        "comparison_sha256", "ordered_run_sha256", "raw_evidence_root_sha256",
        "observed_at_unix_seconds",
    }
    if set(claim) != expected_keys:
        raise InvalidEvidence("observer claim has missing or unknown fields")
    observer = claim["observer_id"]
    producer = claim["producer_id"]
    if (
        not isinstance(observer, str) or not observer or len(observer) > 256
        or not isinstance(producer, str) or not producer or len(producer) > 256
        or observer == producer
    ):
        raise InvalidEvidence("observer must have a distinct bounded identity")
    if (
        type(claim["observed_at_unix_seconds"]) is not int
        or claim["observed_at_unix_seconds"] <= 0
    ):
        raise InvalidEvidence("observer timestamp must be positive")
    for label in (
        "matrix_sha256", "comparison_sha256", "ordered_run_sha256",
        "raw_evidence_root_sha256",
    ):
        require_digest(claim[label], label)
    for label in ("source_sha", "hardware_id", "model_digest", "workload_digest"):
        if claim[label] != matrix[label]:
            raise InvalidEvidence(f"observer {label} does not bind the measured matrix")
    if claim[TRACE_FIELD] != computed[TRACE_FIELD]:
        raise InvalidEvidence("observer request trace does not bind the frozen workload")
    # The ordered list prevents both run elision and ambiguity from JSON array
    # order, including a swapped or duplicated scope/mode observation.
    runs = {(row["scopes"], row["mode"]): row for row in matrix["runs"]}
    ordered = [
        {"scopes": scope, "mode": mode, "measurement_sha256": digest(runs[(scope, mode)])}
        for scope in SCOPES for mode in MODES
    ]
    if (
        claim["matrix_sha256"] != digest(matrix)
        or claim["comparison_sha256"] != digest(comparison)
        or claim["ordered_run_sha256"] != digest(ordered)
    ):
        raise InvalidEvidence("observer evidence digests do not match exact contents")
    verify_signature(
        SIGNING_DOMAIN + canonical_bytes(claim),
        signed.get("signature_base64"),
        public_key,
        pinned_key_sha256,
    )
    return {
        "schema": "hepta.cell-split.observer-verification.v1",
        "source_sha": matrix["source_sha"],
        "matrix_sha256": claim["matrix_sha256"],
        "raw_evidence_root_sha256": claim["raw_evidence_root_sha256"],
        "observer_id": observer,
        "observer_signature_verified": True,
        "exact_matrix_binding_verified": True,
        "comparative_gate_passed": computed["comparative_gate_passed"],
        "host_attestation_verified": False,
        "future_windows_verified": False,
        "production_activation_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--signed-observer", required=True, type=Path)
    parser.add_argument("--observer-public-key", required=True, type=Path)
    parser.add_argument("--pinned-observer-key-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_observer_packet(
            read_json(args.matrix),
            read_json(args.comparison),
            read_json(args.signed_observer),
            args.observer_public_key,
            args.pinned_observer_key_sha256,
        )
    except (OSError, TypeError, KeyError, ValueError, InvalidEvidence) as error:
        parser.error(str(error))
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
