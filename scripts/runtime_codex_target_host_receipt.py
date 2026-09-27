#!/usr/bin/env python3
"""Verify an externally produced runtime.codex target-host receipt.

The real-effect harness is intentionally outside the repository-controlled
process. This verifier consumes its evidence, verifies an Ed25519 signature via
OpenSSL, enforces the closed-world claim boundary and checks every retained
artifact digest. It never creates a production receipt itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "hepta.runtime-codex.target-host-qualification.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX128 = re.compile(r"^[0-9a-f]{128}$")
REQUIRED_FAULTS = {
    "provider_ack_loss",
    "provider_event_lag",
    "app_server_process_loss",
    "agentd_process_loss",
    "worker_process_loss",
    "restart_reconciliation",
    "duplicate_owner",
    "stale_revision",
    "authority_revocation_race",
    "authority_rollback",
    "socket_replacement",
    "disk_full",
    "journal_fsync_failure",
}
REQUIRED_LATENCIES = {
    "authority_claim_ms",
    "durable_prepare_ms",
    "turn_start_ack_ms",
    "first_token_ms",
    "last_token_ms",
    "terminal_event_ms",
    "reconciliation_ms",
}


class ReceiptError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def full_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HEX40.fullmatch(value):
        raise ReceiptError(f"{field} is not a full Git SHA")
    return value


def sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value) or set(value) == {"0"}:
        raise ReceiptError(f"{field} is not a non-zero SHA-256 digest")
    return value


def positive(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReceiptError(f"{field} must be a positive integer")
    return value


def bounded_text(value: Any, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ReceiptError(f"{field} is missing or out of bounds")
    return value


def canonical_payload(receipt: dict[str, Any]) -> bytes:
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_signature(receipt: dict[str, Any], public_key: Path) -> None:
    signature = receipt.get("signature")
    if not isinstance(signature, dict) or set(signature) != {"algorithm", "value"}:
        raise ReceiptError("signature must contain exactly algorithm and value")
    if signature.get("algorithm") != "ed25519":
        raise ReceiptError("only Ed25519 target-host receipts are accepted")
    value = signature.get("value")
    if not isinstance(value, str) or not HEX128.fullmatch(value):
        raise ReceiptError("invalid Ed25519 signature encoding")
    if not public_key.is_file():
        raise ReceiptError("target-host receipt public key is missing")
    with tempfile.TemporaryDirectory(prefix="runtime-codex-receipt-") as directory:
        root = Path(directory)
        payload_path = root / "payload.bin"
        signature_path = root / "signature.bin"
        payload_path.write_bytes(canonical_payload(receipt))
        signature_path.write_bytes(bytes.fromhex(value))
        completed = subprocess.run(
            (
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-sigfile",
                str(signature_path),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise ReceiptError(
                "target-host receipt signature verification failed: "
                + completed.stderr.decode(errors="replace").strip()
            )


def verify_evidence(receipt: dict[str, Any], evidence_root: Path) -> None:
    entries = receipt.get("evidence")
    if not isinstance(entries, list) or not (1 <= len(entries) <= 256):
        raise ReceiptError("evidence inventory must contain 1..256 entries")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ReceiptError(f"evidence[{index}] is not an object")
        relative = bounded_text(entry.get("path"), f"evidence[{index}].path", 1024)
        if relative.startswith("/") or ".." in Path(relative).parts or relative in seen:
            raise ReceiptError(f"unsafe or duplicate evidence path: {relative}")
        seen.add(relative)
        expected = sha256(entry.get("sha256"), f"evidence[{index}].sha256")
        expected_bytes = positive(entry.get("bytes"), f"evidence[{index}].bytes")
        path = evidence_root / relative
        if not path.is_file() or path.is_symlink():
            raise ReceiptError(f"evidence file is missing or unsafe: {relative}")
        data = path.read_bytes()
        if len(data) != expected_bytes or digest(data) != expected:
            raise ReceiptError(f"evidence digest mismatch: {relative}")


def verify_percentiles(value: Any, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"p50", "p95", "p99"}:
        raise ReceiptError(f"{field} must contain exactly p50/p95/p99")
    samples = []
    for name in ("p50", "p95", "p99"):
        point = value[name]
        if not isinstance(point, (int, float)) or isinstance(point, bool) or point < 0:
            raise ReceiptError(f"{field}.{name} is invalid")
        samples.append(float(point))
    if samples != sorted(samples):
        raise ReceiptError(f"{field} percentiles are not monotonic")


def verify_receipt(
    path: Path,
    evidence_root: Path,
    public_key: Path,
    expected_source_sha: str,
    expected_source_tree: str,
    expected_harness_sha256: str,
) -> None:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ReceiptError("receipt root is not an object")
    if receipt.get("schema") != SCHEMA or receipt.get("module") != "runtime.codex":
        raise ReceiptError("unsupported target-host receipt")
    if full_sha(receipt.get("sourceSha"), "sourceSha") != expected_source_sha:
        raise ReceiptError("receipt source SHA does not match the requested candidate")
    if full_sha(receipt.get("sourceTree"), "sourceTree") != expected_source_tree:
        raise ReceiptError("receipt source tree does not match the requested candidate")
    if sha256(receipt.get("harnessSha256"), "harnessSha256") != expected_harness_sha256:
        raise ReceiptError("unapproved target-host harness executed")

    host = receipt.get("host")
    if not isinstance(host, dict):
        raise ReceiptError("host identity is missing")
    bounded_text(host.get("architecture"), "host.architecture", 64)
    bounded_text(host.get("kernelRelease"), "host.kernelRelease", 256)
    sha256(host.get("machineIdSha256"), "host.machineIdSha256")
    sha256(host.get("bootIdSha256"), "host.bootIdSha256")
    sha256(host.get("imageSha256"), "host.imageSha256")

    agent = receipt.get("agent")
    if not isinstance(agent, dict):
        raise ReceiptError("Agentd identity is missing")
    bounded_text(agent.get("agentId"), "agent.agentId", 128)
    positive(agent.get("generation"), "agent.generation")
    sha256(agent.get("binarySha256"), "agent.binarySha256")
    sha256(agent.get("controlSocketIdentitySha256"), "agent.controlSocketIdentitySha256")
    sha256(agent.get("appServerSocketIdentitySha256"), "agent.appServerSocketIdentitySha256")
    positive(agent.get("processId"), "agent.processId")
    positive(agent.get("processStartTicks"), "agent.processStartTicks")

    issuer = receipt.get("issuer")
    if not isinstance(issuer, dict):
        raise ReceiptError("issuer identity is missing")
    bounded_text(issuer.get("signerId"), "issuer.signerId", 128)
    sha256(issuer.get("verifyingKeySha256"), "issuer.verifyingKeySha256")
    positive(issuer.get("authorityEpoch"), "issuer.authorityEpoch")
    positive(issuer.get("revocationRevision"), "issuer.revocationRevision")
    sha256(issuer.get("socketIdentitySha256"), "issuer.socketIdentitySha256")
    sha256(issuer.get("peerExecutableSha256"), "issuer.peerExecutableSha256")
    sha256(issuer.get("peerCgroupSha256"), "issuer.peerCgroupSha256")
    positive(issuer.get("peerPid"), "issuer.peerPid")
    positive(issuer.get("peerStartTicks"), "issuer.peerStartTicks")

    provider = receipt.get("provider")
    if not isinstance(provider, dict) or provider.get("realProvider") is not True:
        raise ReceiptError("receipt does not prove a real provider")
    bounded_text(provider.get("providerId"), "provider.providerId", 128)
    sha256(provider.get("profileSha256"), "provider.profileSha256")
    if provider.get("idempotencyLookupQualified") is not True:
        raise ReceiptError("provider negative/terminal lookup is not qualified")

    faults = receipt.get("faultMatrix")
    if not isinstance(faults, dict) or set(faults) != REQUIRED_FAULTS:
        raise ReceiptError("target-host fault matrix is incomplete")
    for name, result in faults.items():
        if not isinstance(result, dict) or result.get("passed") is not True:
            raise ReceiptError(f"fault case did not pass: {name}")
        sha256(result.get("evidenceSha256"), f"faultMatrix.{name}.evidenceSha256")
        positive(result.get("observations"), f"faultMatrix.{name}.observations")

    performance = receipt.get("performance")
    if not isinstance(performance, dict):
        raise ReceiptError("performance profile is missing")
    if positive(performance.get("samples"), "performance.samples") < 30:
        raise ReceiptError("performance profile has fewer than 30 samples")
    latencies = performance.get("latencies")
    if not isinstance(latencies, dict) or set(latencies) != REQUIRED_LATENCIES:
        raise ReceiptError("latency profile is incomplete")
    for name, points in latencies.items():
        verify_percentiles(points, f"performance.latencies.{name}")
    resources = performance.get("resources")
    if not isinstance(resources, dict):
        raise ReceiptError("resource profile is missing")
    for name in ("peakRssBytes", "peakCpuMillis", "maxOpenFiles", "journalGrowthBytes"):
        positive(resources.get(name), f"performance.resources.{name}")

    for section in ("canary", "rollback", "antiRollbackRecovery"):
        value = receipt.get(section)
        if not isinstance(value, dict) or value.get("passed") is not True:
            raise ReceiptError(f"{section} did not pass")
        sha256(value.get("evidenceSha256"), f"{section}.evidenceSha256")
    if positive(receipt["canary"].get("operations"), "canary.operations") < 1:
        raise ReceiptError("canary contains no operations")
    if receipt["canary"].get("duplicatePhysicalSends") != 0:
        raise ReceiptError("canary observed duplicate physical sends")

    claims = receipt.get("claims")
    expected_true = {
        "targetHostQualified",
        "realProviderQualified",
        "faultMatrixQualified",
        "performanceQualified",
        "canaryQualified",
        "rollbackQualified",
        "antiRollbackRecoveryQualified",
    }
    expected_false = {"independentAcceptance", "activation", "promotion", "release"}
    if not isinstance(claims, dict) or set(claims) != expected_true | expected_false:
        raise ReceiptError("claim boundary is incomplete or contains unknown claims")
    if any(claims[name] is not True for name in expected_true):
        raise ReceiptError("qualified target-host claim is false")
    if any(claims[name] is not False for name in expected_false):
        raise ReceiptError("target-host receipt illegally grants acceptance or release")

    issued = positive(receipt.get("issuedAtUnixMs"), "issuedAtUnixMs")
    expires = positive(receipt.get("expiresAtUnixMs"), "expiresAtUnixMs")
    if expires <= issued or expires - issued > 7 * 24 * 60 * 60 * 1000:
        raise ReceiptError("receipt validity window is invalid")
    sha256(receipt.get("nonceSha256"), "nonceSha256")

    verify_evidence(receipt, evidence_root)
    verify_signature(receipt, public_key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--harness-sha256", required=True)
    args = parser.parse_args()
    try:
        verify_receipt(
            args.receipt,
            args.evidence_root,
            args.public_key,
            full_sha(args.source_sha, "expected sourceSha"),
            full_sha(args.source_tree, "expected sourceTree"),
            sha256(args.harness_sha256, "expected harnessSha256"),
        )
        return 0
    except (ReceiptError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"runtime.codex target-host receipt error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
