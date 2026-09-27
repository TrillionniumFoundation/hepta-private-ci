#!/usr/bin/env python3
"""Independent exact-candidate native feedback.

All native checks run and every failure remains a failure.  The per-candidate
receipt binds source identity, toolchain/runtime identity, dependency lock,
canonical module manifest, and the fixed provider binary observation.  A
separate paired attestation combines source-head and deterministic synthetic
merge receipts without putting self-referential commit IDs in documentation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "codex-rs/Cargo.lock"
MANIFEST = ROOT / "docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json"
PROVIDER_EVIDENCE = (
    ROOT
    / "codex-rs/hepta-bao-adapter/qa/evidence/dynamic-contract-probe-20260925.json"
)
CHECKS = [
    (
        "format",
        [
            "cargo",
            "fmt",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-hepta-authbus",
            "-p",
            "codex-state-sqlite",
            "--",
            "--check",
        ],
    ),
    (
        "tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-state-sqlite",
            "--all-targets",
            "--",
            "--test-threads=2",
        ],
    ),
    (
        "clippy",
        [
            "cargo",
            "clippy",
            "--locked",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-state-sqlite",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ],
    ),
    (
        "authbus-schema",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-authbus",
            "authority_schema",
            "--",
            "--test-threads=2",
        ],
    ),
]


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_identity(command: list[str]) -> str:
    return subprocess.check_output(
        command,
        cwd=ROOT / "codex-rs",
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def runtime_identity() -> dict[str, object]:
    return {
        "toolchain": {
            "rustc": command_identity(["rustc", "-Vv"]),
            "cargo": command_identity(["cargo", "-V"]),
        },
        "os": platform.platform(),
        "architecture": platform.machine(),
    }


def provider_identity() -> dict[str, object]:
    evidence = json.loads(PROVIDER_EVIDENCE.read_text(encoding="utf-8"))
    binary = evidence.get("serverSha256")
    source = evidence.get("providerCommit")
    if (
        not isinstance(binary, str)
        or len(binary) != 64
        or any(character not in "0123456789abcdef" for character in binary)
        or not isinstance(source, str)
        or len(source) != 40
    ):
        raise ValueError("fixed provider evidence lacks a valid binary/source identity")
    return {
        "providerBinarySha256": binary,
        "providerSourceCommit": source,
        "providerEvidenceSha256": sha256_file(PROVIDER_EVIDENCE),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--candidate-role",
        choices=["source-head", "synthetic-merge"],
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    before = git("status", "--porcelain", "--untracked-files=no")
    runtime = runtime_identity()
    provider = provider_identity()
    candidate_identity = {
        "role": args.candidate_role,
        "commitSha": head,
        "treeSha": tree,
        **runtime,
        "dependencyLockSha256": sha256_file(LOCK),
        **provider,
        "manifestSha256": sha256_file(MANIFEST),
    }

    results = []
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    environment.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
    for name, command in CHECKS:
        start = time.monotonic()
        log = args.output / f"{name}.log"
        with log.open("wb") as stream:
            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT / "codex-rs",
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=3000,
                    check=False,
                )
                code = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                stream.write(f"\nqualification command failed: {error}\n".encode())
                code = 124 if isinstance(error, subprocess.TimeoutExpired) else 127
        results.append(
            {
                "check": name,
                "command": command,
                "exitCode": code,
                "durationSeconds": round(time.monotonic() - start, 3),
                "logSha256": sha256_file(log),
            }
        )
        print(f"{name}: exit {code}", flush=True)

    after = git("status", "--porcelain", "--untracked-files=no")
    identity_ok = (
        head == args.expected_sha
        and not before
        and not after
        and head == git("rev-parse", "HEAD")
        and tree == git("rev-parse", "HEAD^{tree}")
    )
    passed = identity_ok and all(row["exitCode"] == 0 for row in results)
    receipt = {
        "schema": "hepta.secrets-native-feedback.v2",
        # Retained aliases keep existing readers deterministic during migration.
        "head": head,
        "tree": tree,
        "expectedSha": args.expected_sha,
        "candidateRole": args.candidate_role,
        "candidateIdentity": candidate_identity,
        "identityClean": identity_ok,
        "trackedChangesBefore": before,
        "trackedChangesAfter": after,
        "checks": results,
        "passed": passed,
        "providerDynamicE2E": False,
        "productionExecutionProved": False,
        "independentAcceptance": False,
        "releaseAuthority": False,
    }
    (args.output / "receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
