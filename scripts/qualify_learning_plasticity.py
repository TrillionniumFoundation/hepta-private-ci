#!/usr/bin/env python3
"""Read-only, exact-candidate plasticity qualification with failure-preserving receipts.

This runner never refreshes documents, fixes source, commits changes or pushes.
A failing command remains failing; subsequent independent gates still run.
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


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    os.chdir(root)
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("evidence must be written outside the candidate checkout")
    output.mkdir(parents=True, exist_ok=True)
    source = os.environ.get("SOURCE_SHA", git("rev-parse", "HEAD"))
    base = os.environ.get("BASE_SHA", source)
    tested = os.environ.get("TESTED_SHA", source)
    if git("rev-parse", "HEAD") != tested or git("status", "--porcelain"):
        raise RuntimeError("candidate is not the exact clean tested commit")
    packages = [
        "codex-hepta-plasticity",
        "codex-hepta-learning-artifacts",
        "codex-hepta-intelligence",
        "codex-hepta-agentd",
    ]
    flags = [item for package in packages for item in ("-p", package)]
    fmt_flags = [item for package in packages for item in ("--package", package)]
    commands = [
        (
            "grammar",
            root,
            ["python3", "scripts/test_learning_plasticity_grammar_contract.py"],
        ),
        ("documents", root, ["python3", "scripts/hepta-docs.py", "verify"]),
        (
            "derived-documents",
            root,
            [
                "python3",
                "scripts/hepta-module-docs.py",
                "refresh-derived",
                "--check",
            ],
        ),
        (
            "implementation-maps",
            root,
            ["python3", "scripts/hepta-implementation-maps.py", "verify"],
        ),
        (
            "format",
            root / "codex-rs",
            [
                "cargo",
                "fmt",
                "--manifest-path",
                "Cargo.toml",
                *fmt_flags,
                "--",
                "--check",
            ],
        ),
        (
            "compile",
            root / "codex-rs",
            ["cargo", "check", "--locked", "--all-targets", *flags],
        ),
        (
            "plasticity-and-artifacts",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-plasticity",
                "-p",
                "codex-hepta-learning-artifacts",
                "--test-threads=1",
            ],
        ),
        (
            "product-admission",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence",
                "--lib",
                "plasticity",
                "--test-threads=1",
            ],
        ),
        (
            "runtime-resource-admission",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "plasticity_aggregate_quota_spans_parameter_and_topology_work",
                "--test-threads=1",
            ],
        ),
        (
            "runtime-recovery-contract",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently",
                "--test-threads=1",
            ],
        ),
        (
            "agentd-lifetime",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "plasticity_",
                "--test-threads=1",
            ],
        ),
        (
            "process-recovery",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--test",
                "plasticity_process_e2e",
                "--test-threads=1",
            ],
        ),
        (
            "runtime-canary",
            root / "codex-rs",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-runtime",
                "authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics",
                "--test-threads=1",
            ],
        ),
        (
            "strict-lint",
            root / "codex-rs",
            ["cargo", "clippy", "--locked", "--all-targets", *flags, "--", "-D", "warnings"],
        ),
        ("diff-check", root, ["git", "diff", "--check"]),
        ("unchanged-tree", root, ["git", "diff", "--exit-code"]),
    ]
    receipt = {
        "schema": "hepta.learning-plasticity-exact-execution.v2",
        "sourceCommit": source,
        "sourceTree": git("rev-parse", f"{source}^{{tree}}"),
        "baseCommit": base,
        "baseTree": git("rev-parse", f"{base}^{{tree}}"),
        "testedCommit": tested,
        "testedTree": git("rev-parse", "HEAD^{tree}"),
        "lane": os.environ.get("LANE", "source-head"),
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflowRun": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerImage": os.environ.get("ImageOS"),
        "runnerImageVersion": os.environ.get("ImageVersion"),
        "platform": platform.platform(),
        "startedAtUnixSeconds": int(time.time()),
        "targetHostEvidence": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "commands": [],
        "passed": False,
    }
    for name, cwd, command in commands:
        log = output / f"{name}.log"
        started = time.monotonic()
        print(f"::group::{name}: {command}", flush=True)
        with log.open("wb") as stream:
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=1800,
                    check=False,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                stream.write(b"\nQUALIFICATION_COMMAND_TIMEOUT\n")
                code = 124
            except OSError as error:
                stream.write(f"{type(error).__name__}: {error}\n".encode())
                code = 127
        raw = log.read_bytes()
        print(raw.decode(errors="replace")[-16000:], flush=True)
        print("::endgroup::", flush=True)
        receipt["commands"].append(
            {
                "name": name,
                "command": command,
                "cwd": str(cwd.relative_to(root)),
                "exitCode": code,
                "durationSeconds": time.monotonic() - started,
                "logSha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        (output / "execution.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
    receipt["candidateUnchanged"] = git("rev-parse", "HEAD") == tested and not git(
        "status", "--porcelain", "--untracked-files=no"
    )
    receipt["passed"] = receipt["candidateUnchanged"] and all(
        row["exitCode"] == 0 for row in receipt["commands"]
    )
    receipt["finishedAtUnixSeconds"] = int(time.time())
    (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
