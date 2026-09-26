#!/usr/bin/env python3
"""Verify an independently signed automation.taskflow acceptance envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    need(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hex(value: Any, label: str, length: int) -> str:
    need(
        isinstance(value, str)
        and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None,
        f"{label} must be exactly {length} lowercase hex characters",
    )
    return value


def require_text(value: Any, label: str, maximum: int = 256) -> str:
    need(
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= maximum
        and value == value.strip()
        and "\x00" not in value,
        f"{label} must be a bounded non-empty string",
    )
    return value


def require_utc_timestamp(value: Any) -> str:
    timestamp = require_text(value, "acceptedAtUtc", 64)
    need(timestamp.endswith("Z"), "acceptedAtUtc must use a UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as error:
        raise AcceptanceError("acceptedAtUtc is not ISO-8601") from error
    need(parsed.tzinfo == timezone.utc, "acceptedAtUtc must be UTC")
    return timestamp


def trusted_public_key_sha256(public_key_pem: Path) -> str:
    result = subprocess.run(
        [
            "openssl",
            "pkey",
            "-pubin",
            "-in",
            str(public_key_pem),
            "-outform",
            "DER",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    need(
        result.returncode == 0,
        "trusted acceptance public key is invalid: "
        + result.stderr.decode("utf-8", errors="replace").strip(),
    )
    return hashlib.sha256(result.stdout).hexdigest()


def verify_ed25519_signature(
    payload_bytes: bytes,
    signature_hex: str,
    public_key_pem: Path,
) -> None:
    signature = bytes.fromhex(require_hex(signature_hex, "signatureHex", 128))
    with tempfile.TemporaryDirectory(prefix="automation-acceptance-") as directory:
        root = Path(directory)
        payload_path = root / "payload.json"
        signature_path = root / "signature.bin"
        payload_path.write_bytes(payload_bytes)
        signature_path.write_bytes(signature)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key_pem),
                "-rawin",
                "-in",
                str(payload_path),
                "-sigfile",
                str(signature_path),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    need(
        result.returncode == 0,
        "independent acceptance signature verification failed",
    )


def verify_acceptance(
    *,
    envelope_path: Path,
    focused_receipt_path: Path,
    selected_host_receipt_path: Path,
    public_key_pem: Path,
    candidate_commit: str,
    candidate_tree: str,
    focused_run_id: str,
    selected_host_run_id: str,
    expected_implementation_principal: str,
    expected_acceptance_principal: str,
) -> dict[str, Any]:
    candidate_commit = require_hex(candidate_commit, "candidate commit", 40)
    candidate_tree = require_hex(candidate_tree, "candidate tree", 40)
    focused_run_id = require_text(focused_run_id, "focused run id", 32)
    selected_host_run_id = require_text(
        selected_host_run_id, "selected-host run id", 32
    )
    expected_implementation_principal = require_text(
        expected_implementation_principal, "expected implementation principal"
    )
    expected_acceptance_principal = require_text(
        expected_acceptance_principal, "expected acceptance principal"
    )
    need(
        expected_implementation_principal != expected_acceptance_principal,
        "implementation and acceptance principals must be distinct",
    )

    focused = read_json(focused_receipt_path)
    need(
        focused.get("schema") == "hepta.automation-taskflow.command-receipt.v1",
        "focused receipt schema mismatch",
    )
    need(focused.get("commit") == candidate_commit, "focused receipt commit mismatch")
    need(focused.get("tree") == candidate_tree, "focused receipt tree mismatch")
    need(str(focused.get("runId")) == focused_run_id, "focused receipt run id mismatch")

    selected = read_json(selected_host_receipt_path)
    need(
        selected.get("schema")
        == "hepta.automation-taskflow.selected-host-receipt.v1",
        "selected-host receipt schema mismatch",
    )
    need(
        selected.get("commit") == candidate_commit,
        "selected-host receipt commit mismatch",
    )
    need(selected.get("tree") == candidate_tree, "selected-host receipt tree mismatch")
    selected_run = selected.get("run")
    need(isinstance(selected_run, dict), "selected-host receipt run block missing")
    need(
        str(selected_run.get("id")) == selected_host_run_id,
        "selected-host receipt run id mismatch",
    )
    target_profile = require_text(selected.get("targetProfile"), "selected target profile")

    selected_provider = require_hex(
        selected.get("providerIdentitySha256"), "selected provider identity", 64
    )
    selected_observer = require_hex(
        selected.get("terminalObserverIdentitySha256"),
        "selected terminal observer identity",
        64,
    )
    selected_trust = require_hex(
        selected.get("finalUseTrustSha256"), "selected final-use trust", 64
    )
    selected_revocation = require_hex(
        selected.get("revocationHeadSha256"), "selected revocation head", 64
    )
    need(
        selected.get("independentAcceptance") is False,
        "selected-host qualification must not self-assert independent acceptance",
    )
    need(
        selected.get("activation") is False,
        "selected-host receipt must keep activation false",
    )
    need(selected.get("release") is False, "selected-host receipt must keep release false")

    envelope = read_json(envelope_path)
    need(
        envelope.get("schema")
        == "hepta.automation-taskflow.independent-acceptance-envelope.v1",
        "acceptance envelope schema mismatch",
    )
    payload = envelope.get("payload")
    need(isinstance(payload, dict), "acceptance envelope payload missing")
    need(
        payload.get("schema")
        == "hepta.automation-taskflow.independent-acceptance-payload.v1",
        "acceptance payload schema mismatch",
    )
    need(payload.get("module") == "automation.taskflow", "acceptance module mismatch")
    need(payload.get("candidateCommit") == candidate_commit, "acceptance commit mismatch")
    need(payload.get("candidateTree") == candidate_tree, "acceptance tree mismatch")
    need(
        str(payload.get("focusedRunId")) == focused_run_id,
        "acceptance focused run mismatch",
    )
    need(
        str(payload.get("selectedHostRunId")) == selected_host_run_id,
        "acceptance selected-host run mismatch",
    )
    need(
        payload.get("targetProfile") == target_profile,
        "acceptance target profile mismatch",
    )
    need(
        payload.get("focusedReceiptSha256") == sha256_file(focused_receipt_path),
        "focused receipt digest mismatch",
    )
    need(
        payload.get("selectedHostReceiptSha256")
        == sha256_file(selected_host_receipt_path),
        "selected-host receipt digest mismatch",
    )
    need(
        payload.get("providerIdentitySha256") == selected_provider,
        "provider identity digest mismatch",
    )
    need(
        payload.get("terminalObserverIdentitySha256") == selected_observer,
        "terminal-observer identity digest mismatch",
    )
    need(
        payload.get("finalUseTrustSha256") == selected_trust,
        "final-use trust digest mismatch",
    )
    need(
        payload.get("revocationHeadSha256") == selected_revocation,
        "revocation-head digest mismatch",
    )
    need(
        payload.get("implementationPrincipal") == expected_implementation_principal,
        "implementation principal mismatch",
    )
    need(
        payload.get("acceptancePrincipal") == expected_acceptance_principal,
        "acceptance principal mismatch",
    )
    need(
        payload.get("implementationPrincipal") != payload.get("acceptancePrincipal"),
        "acceptance is not independent",
    )
    need(payload.get("decision") == "accepted", "acceptance decision is not accepted")
    need(
        payload.get("independentAcceptance") is True,
        "independentAcceptance must be true in the signed payload",
    )
    require_utc_timestamp(payload.get("acceptedAtUtc"))
    require_text(payload.get("nonce"), "acceptance nonce", 128)

    key_digest = trusted_public_key_sha256(public_key_pem)
    need(
        payload.get("acceptanceKeySha256") == key_digest,
        "acceptance key fingerprint mismatch",
    )
    verify_ed25519_signature(
        canonical_payload_bytes(payload),
        envelope.get("signatureHex"),
        public_key_pem,
    )

    return {
        "schema": "hepta.automation-taskflow.independent-acceptance-verification.v1",
        "module": "automation.taskflow",
        "candidateCommit": candidate_commit,
        "candidateTree": candidate_tree,
        "focusedRunId": focused_run_id,
        "selectedHostRunId": selected_host_run_id,
        "targetProfile": target_profile,
        "implementationPrincipal": expected_implementation_principal,
        "acceptancePrincipal": expected_acceptance_principal,
        "acceptanceKeySha256": key_digest,
        "envelopeSha256": sha256_file(envelope_path),
        "focusedReceiptSha256": sha256_file(focused_receipt_path),
        "selectedHostReceiptSha256": sha256_file(selected_host_receipt_path),
        "independentAcceptance": True,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--focused-receipt", type=Path, required=True)
    parser.add_argument("--selected-host-receipt", type=Path, required=True)
    parser.add_argument("--public-key-pem", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--focused-run-id", required=True)
    parser.add_argument("--selected-host-run-id", required=True)
    parser.add_argument("--implementation-principal", required=True)
    parser.add_argument("--acceptance-principal", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_acceptance(
            envelope_path=args.envelope,
            focused_receipt_path=args.focused_receipt,
            selected_host_receipt_path=args.selected_host_receipt,
            public_key_pem=args.public_key_pem,
            candidate_commit=args.candidate_commit,
            candidate_tree=args.candidate_tree,
            focused_run_id=args.focused_run_id,
            selected_host_run_id=args.selected_host_run_id,
            expected_implementation_principal=args.implementation_principal,
            expected_acceptance_principal=args.acceptance_principal,
        )
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AcceptanceError, OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"automation.taskflow independent acceptance verification failed: {error}"
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
