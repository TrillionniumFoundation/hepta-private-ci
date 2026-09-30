#!/usr/bin/env python3
'''Independent exact-source native feedback.

All checks run, failures remain failures, and the checkout must stay fully clean.
The script never materializes, commits or pushes source.
'''
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
RUST = ROOT / "codex-rs"

CHECKS = [
    (
        "build-contract",
        ROOT,
        [
            "python3",
            "codex-rs/hepta-bao-adapter/qa/validate_build_contract.py",
        ],
    ),
    (
        "manifest-projections",
        ROOT,
        ["python3", "scripts/generate_secrets_heptabao_module.py"],
    ),
    (
        "cargo-metadata",
        RUST,
        [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--no-deps",
        ],
    ),
    (
        "format",
        RUST,
        [
            "cargo",
            "fmt",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-hepta-authbus",
            "-p",
            "codex-state-sqlite",
            "-p",
            "codex-hepta-types",
            "--",
            "--check",
        ],
    ),
    (
        "all-target-check",
        RUST,
        [
            "cargo",
            "check",
            "--locked",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-state-sqlite",
            "-p",
            "codex-hepta-types",
            "--all-targets",
        ],
    ),
    (
        "tests",
        RUST,
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-state-sqlite",
            "-p",
            "codex-hepta-types",
            "--all-targets",
            "--",
            "--test-threads=2",
        ],
    ),
    (
        "clippy",
        RUST,
        [
            "cargo",
            "clippy",
            "--locked",
            "-p",
            "codex-hepta-bao-adapter",
            "-p",
            "codex-state-sqlite",
            "-p",
            "codex-hepta-types",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ],
    ),
    (
        "authbus-schema",
        RUST,
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
    (
        "authbus-operation",
        RUST,
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-authbus",
            "operation_lookup",
            "--",
            "--test-threads=2",
        ],
    ),
]


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=True,
    ).strip()


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
    before = git("status", "--porcelain=v1", "--untracked-files=all")
    diff_check_before = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    results: list[dict[str, object]] = []
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    environment.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
    try:
        rust_toolchain = subprocess.check_output(
            ["rustc", "--version", "--verbose"], cwd=RUST, env=environment, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        rust_toolchain = f"unavailable: {error}"

    for name, cwd, command in CHECKS:
        start = time.monotonic()
        log = args.output / f"{name}.log"
        with log.open("wb") as stream:
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=3000,
                    check=False,
                )
                code = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                stream.write(
                    f"\nqualification command failed: {error}\n".encode()
                )
                code = (
                    124
                    if isinstance(error, subprocess.TimeoutExpired)
                    else 127
                )
        results.append(
            {
                "check": name,
                "command": command,
                "exitCode": code,
                "durationSeconds": round(
                    time.monotonic() - start, 3
                ),
                "logSha256": hashlib.sha256(
                    log.read_bytes()
                ).hexdigest(),
            }
        )
        print(f"{name}: exit {code}", flush=True)

    after = git("status", "--porcelain=v1", "--untracked-files=all")
    diff_check_after = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    identity_ok = (
        head == args.expected_sha
        and not before
        and not after
        and diff_check_before.returncode == 0
        and diff_check_after.returncode == 0
        and head == git("rev-parse", "HEAD")
    )
    passed = identity_ok and rust_toolchain.startswith("rustc ") and all(
        row["exitCode"] == 0 for row in results
    )
    receipt = {
        "schema": "hepta.secrets-native-feedback.v2",
        "head": head,
        "tree": tree,
        "expectedSha": args.expected_sha,
        "candidateRole": args.candidate_role,
        "workflowRunId": environment.get("GITHUB_RUN_ID", "local"),
        "workflowAttempt": environment.get("GITHUB_RUN_ATTEMPT", "local-1"),
        "workflowSha": environment.get("GITHUB_WORKFLOW_SHA", head),
        "rustToolchain": rust_toolchain,
        "buildSurface": "single_complete",
        "identityClean": identity_ok,
        "trackedAndUntrackedBefore": before,
        "trackedAndUntrackedAfter": after,
        "diffCheckBefore": diff_check_before.returncode,
        "diffCheckAfter": diff_check_after.returncode,
        "checks": results,
        "passed": passed,
        "providerDynamicE2E": False,
        "productionExecutionProved": False,
        "storageProfileQualified": False,
        "productComposed": False,
        "independentAcceptance": False,
        "releaseAuthority": False,
    }
    (args.output / "receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
