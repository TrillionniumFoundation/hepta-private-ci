#!/usr/bin/env python3
"""Bind selected-host TaskFlow evidence to the exact bytes consumed by Rust.

This tool does not grant independent acceptance, activation, promotion, or
release. It derives deployment identity digests from protected files, verifies
that the Rust qualification receipts consumed those same bytes, and emits one
exact-candidate selected-host receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

DIGEST_RE = re.compile(r"[0-9a-f]{64}")
MAX_CONFIG_BYTES = 4 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def identity_digest(domain: str, value: Any) -> str:
    return sha256_bytes(domain.encode() + b"\0" + canonical_json(value))


def read_file(path: Path, *, protected: bool, max_bytes: int = MAX_CONFIG_BYTES) -> bytes:
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {path}")
    canonical = path.resolve(strict=True)
    if canonical != path:
        raise ValueError(f"path must be canonical and symlink-free: {path}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError(f"path must be a regular non-symlink file: {path}")
    if info.st_size <= 0 or info.st_size > max_bytes:
        raise ValueError(f"file is empty or exceeds {max_bytes} bytes: {path}")
    if protected and info.st_mode & 0o077:
        raise ValueError(f"protected file must not be group/world accessible: {path}")
    if not protected and info.st_mode & 0o022:
        raise ValueError(f"immutable file must not be group/world writable: {path}")
    return path.read_bytes()


def read_json(path: Path, *, protected: bool) -> tuple[dict[str, Any], bytes]:
    raw = read_file(path, protected=protected)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value, raw


def require_digest(value: str, label: str) -> str:
    if DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def tzdb_tree_digest(root: Path) -> str:
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("tzdb root must be an absolute canonical directory")
    entries: list[tuple[str, str, str]] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, "file", sha256_bytes(path.read_bytes())))
    if not entries:
        raise ValueError("tzdb root contains no files or symlinks")
    digest = hashlib.sha256(b"hepta.automation.tzdb-tree.v1\0")
    for relative, kind, value in sorted(entries):
        for field in (relative, kind, value):
            encoded = field.encode()
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def input_facts(args: argparse.Namespace) -> dict[str, Any]:
    tzdb_root = Path(args.tzdb_root)
    tzdb_sha = tzdb_tree_digest(tzdb_root)
    require_digest(args.expected_tzdb_sha256, "expected_tzdb_sha256")
    if tzdb_sha != args.expected_tzdb_sha256:
        raise ValueError("selected-host tzdb bytes differ from the requested digest")
    timezone_profile, timezone_raw = read_json(Path(args.timezone_profile), protected=False)
    effect_host, effect_host_raw = read_json(Path(args.effect_host), protected=True)
    terminal_observer, terminal_raw = read_json(Path(args.terminal_observer), protected=True)
    revocations_path = Path(str(effect_host["final_use_revocations_file"]))
    _, revocations_raw = read_json(revocations_path, protected=True)
    if timezone_profile.get("tzdb_digest") != tzdb_sha:
        raise ValueError("timezone profile is not bound to the selected-host tzdb tree")
    if terminal_observer.get("schema_version") != 1:
        raise ValueError("unsupported terminal-observer profile schema")
    return {
        "tzdbSha256": tzdb_sha,
        "timezoneProfileSha256": sha256_bytes(timezone_raw),
        "timezoneId": timezone_profile.get("timezone_id"),
        "effectHostSha256": sha256_bytes(effect_host_raw),
        "terminalObserverSha256": sha256_bytes(terminal_raw),
        "revocationsSha256": sha256_bytes(revocations_raw),
        "revocationsPath": str(revocations_path),
    }


def derive_provider_identity(host: dict[str, Any]) -> str:
    headers = host.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError("effect-host headers must be an object")
    header_identity = [
        {"name": str(name).lower(), "valueSha256": sha256_bytes(str(value).encode())}
        for name, value in sorted(headers.items())
    ]
    provider = {
        "providerScope": host["provider_scope"],
        "destinationId": host["destination_id"],
        "dispatchUrl": host["dispatch_url"],
        "lookupUrlTemplate": host["lookup_url_template"],
        "timeoutMs": host["timeout_ms"],
        "contractId": host["contract_id"],
        "contractSha256": require_digest(host["contract_sha256"], "contract_sha256"),
        "contractAuthorityEpoch": host["contract_authority_epoch"],
        "contractVerifyingKeyHex": host["contract_verifying_key_hex"],
        "headers": header_identity,
    }
    return identity_digest("hepta.automation.provider-identity.v1", provider)


def derive_final_use_trust_identity(host: dict[str, Any]) -> str:
    trust = {
        "signerId": host["final_use_signer_id"],
        "verifyingKeyHex": host["final_use_verifying_key_hex"],
        "scopeSha256": require_digest(host["final_use_scope_sha256"], "final_use_scope_sha256"),
    }
    return identity_digest("hepta.automation.final-use-trust.v1", trust)


def verify_rust_receipts(
    timezone_receipt: dict[str, Any],
    effect_receipt: dict[str, Any],
    *,
    timezone_profile_sha: str,
    tzdb_sha: str,
    effect_host_sha: str,
    revocations_sha: str,
    terminal_sha: str,
) -> None:
    expected_timezone = {
        "profileSha256": timezone_profile_sha,
        "tzdbSha256": tzdb_sha,
        "rustConsumed": True,
    }
    for key, expected in expected_timezone.items():
        if timezone_receipt.get(key) != expected:
            raise ValueError(f"timezone Rust receipt mismatch for {key}")
    expected_effect = {
        "effectHostSha256": effect_host_sha,
        "revocationsSha256": revocations_sha,
        "terminalObserverSha256": terminal_sha,
        "productConfigurationLoaded": True,
    }
    for key, expected in expected_effect.items():
        if effect_receipt.get(key) != expected:
            raise ValueError(f"effect-host Rust receipt mismatch for {key}")


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    candidate = args.candidate_sha
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise ValueError("candidate_sha must be a lowercase Git commit SHA")
    if git("rev-parse", "HEAD") != candidate:
        raise ValueError("checked-out HEAD differs from candidate_sha")

    tzdb_root = Path(args.tzdb_root)
    tzdb_sha = tzdb_tree_digest(tzdb_root)
    require_digest(args.expected_tzdb_sha256, "expected_tzdb_sha256")
    if tzdb_sha != args.expected_tzdb_sha256:
        raise ValueError("selected-host tzdb bytes differ from the requested digest")

    timezone_profile, timezone_raw = read_json(Path(args.timezone_profile), protected=False)
    effect_host, effect_host_raw = read_json(Path(args.effect_host), protected=True)
    terminal_observer, terminal_raw = read_json(Path(args.terminal_observer), protected=True)
    revocations_path = Path(str(effect_host["final_use_revocations_file"]))
    revocations, revocations_raw = read_json(revocations_path, protected=True)

    timezone_profile_sha = sha256_bytes(timezone_raw)
    effect_host_sha = sha256_bytes(effect_host_raw)
    terminal_sha = sha256_bytes(terminal_raw)
    revocations_sha = sha256_bytes(revocations_raw)

    if timezone_profile.get("tzdb_digest") != tzdb_sha:
        raise ValueError("timezone profile is not bound to the selected-host tzdb tree")
    if terminal_observer.get("schema_version") != 1:
        raise ValueError("unsupported terminal-observer profile schema")
    if terminal_observer.get("protocol") != "thread/queue/reconcile+thread/turns/list@v2":
        raise ValueError("terminal observer profile does not name the product reconciliation path")
    if not isinstance(revocations.get("authority_epoch"), int) or not isinstance(
        revocations.get("revision"), int
    ):
        raise ValueError("revocation head is missing authority_epoch/revision")

    timezone_rust, _ = read_json(Path(args.timezone_rust_receipt), protected=False)
    effect_rust, _ = read_json(Path(args.effect_rust_receipt), protected=False)
    verify_rust_receipts(
        timezone_rust,
        effect_rust,
        timezone_profile_sha=timezone_profile_sha,
        tzdb_sha=tzdb_sha,
        effect_host_sha=effect_host_sha,
        revocations_sha=revocations_sha,
        terminal_sha=terminal_sha,
    )

    provider_identity = derive_provider_identity(effect_host)
    final_use_trust = derive_final_use_trust_identity(effect_host)
    terminal_identity = identity_digest(
        "hepta.automation.terminal-observer-identity.v1", terminal_observer
    )

    release = "unknown"
    tzdata_zi = tzdb_root / "tzdata.zi"
    if tzdata_zi.is_file():
        release = tzdata_zi.read_text(encoding="utf-8", errors="replace").splitlines()[0]

    return {
        "schema": "hepta.automation-taskflow.selected-host-receipt.v2",
        "commit": candidate,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "targetProfile": args.target_profile,
        "providerIdentitySha256": provider_identity,
        "terminalObserverIdentitySha256": terminal_identity,
        "finalUseTrustSha256": final_use_trust,
        "revocationHeadSha256": revocations_sha,
        "inputs": {
            "timezoneProfileSha256": timezone_profile_sha,
            "effectHostFileSha256": effect_host_sha,
            "terminalObserverFileSha256": terminal_sha,
            "revocationsFileSha256": revocations_sha,
        },
        "revocationHead": {
            "authorityEpoch": revocations["authority_epoch"],
            "revision": revocations["revision"],
        },
        "host": {
            "node": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "sqliteRuntimeVersion": timezone_rust["sqliteRuntimeVersion"],
        },
        "tzdb": {
            "root": str(tzdb_root),
            "sha256": tzdb_sha,
            "release": release,
            "timezoneId": timezone_rust["timezoneId"],
            "transitionCount": timezone_rust["transitionCount"],
        },
        "rustEvidence": {
            "timezone": timezone_rust,
            "effectHost": effect_rust,
        },
        "run": {
            "id": os.environ.get("GITHUB_RUN_ID"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "runnerName": os.environ.get("RUNNER_NAME"),
            "runnerOs": os.environ.get("RUNNER_OS"),
            "runnerArch": os.environ.get("RUNNER_ARCH"),
        },
        "qualified": [
            "schema-v22-drift",
            "actual-timezone-profile-rust-consumption",
            "actual-provider-final-use-revocation-rust-load",
            "native-sqlite-runtime-identity",
            "multi-scheduler-race",
            "crash-reopen-unknown-result",
            "persistent-neural-circuit-recovery",
            "signed-cross-host-fence-contract",
        ],
        "deploymentQualificationComplete": False,
        "independentAcceptance": False,
        "activation": False,
        "promotion": False,
        "release": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    tzdb = sub.add_parser("tzdb-digest")
    tzdb.add_argument("--root", required=True)

    facts = sub.add_parser("facts")
    facts.add_argument("--tzdb-root", required=True)
    facts.add_argument("--expected-tzdb-sha256", required=True)
    facts.add_argument("--timezone-profile", required=True)
    facts.add_argument("--effect-host", required=True)
    facts.add_argument("--terminal-observer", required=True)

    receipt = sub.add_parser("receipt")
    receipt.add_argument("--candidate-sha", required=True)
    receipt.add_argument("--target-profile", required=True)
    receipt.add_argument("--tzdb-root", required=True)
    receipt.add_argument("--expected-tzdb-sha256", required=True)
    receipt.add_argument("--timezone-profile", required=True)
    receipt.add_argument("--effect-host", required=True)
    receipt.add_argument("--terminal-observer", required=True)
    receipt.add_argument("--timezone-rust-receipt", required=True)
    receipt.add_argument("--effect-rust-receipt", required=True)
    receipt.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "tzdb-digest":
        print(tzdb_tree_digest(Path(args.root)))
        return 0
    if args.command == "facts":
        print(json.dumps(input_facts(args), sort_keys=True))
        return 0
    receipt = build_receipt(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
