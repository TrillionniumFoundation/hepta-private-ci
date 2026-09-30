#!/usr/bin/env python3
"""Exact-source selected-only writer and durable ledger qualification.

This is not a substitute for the full source/merge qualification or target-host
operator acceptance. All product tests are mandatory, including V3 and commit
boundaries. Failures retain their command logs outside the checkout.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import sys
import time

import intuition_qualify_exact as q

COMMANDS = [
    (
        "ledger-production-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-learning-ledger",
            "production",
        ],
    ),
    (
        "ledger-trust-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-learning-ledger",
            "--lib",
            "trust_distribution",
        ],
    ),
    (
        "agentd-selected-only-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--lib",
            "intuition_policy",
        ],
    ),
    (
        "agentd-product-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--test",
            "intuition_policy_product",
        ],
    ),
    (
        "agentd-v3-product-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--test",
            "intuition_policy_product_v3",
        ],
    ),
    (
        "agentd-commit-boundary-tests",
        [
            "cargo",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--test",
            "intuition_policy_commit_boundary",
        ],
    ),
    (
        "durable-ledger-benchmark",
        [
            "cargo",
            "run",
            "--locked",
            "--release",
            "-p",
            "codex-hepta-learning-ledger",
            "--example",
            "target_host_qualification",
        ],
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--command-timeout", type=int, default=2400)
    args = parser.parse_args(argv)
    if args.command_timeout < 1:
        parser.error("--command-timeout must be positive")
    try:
        evidence = q.external_directory(args.evidence)
    except ValueError as error:
        parser.error(str(error))
    head, tree = q.git("rev-parse", "HEAD"), q.git("rev-parse", "HEAD^{tree}")
    record = {
        "schema": "hepta.intuition.ledger-command-record.v1",
        "sourceSha": args.source_commit,
        "testedSha": head,
        "testedTree": tree,
        "scope": "selected-only-product-and-durable-ledger",
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "jobId": os.environ.get("GITHUB_JOB"),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "host": platform.platform(),
        "startedAt": q.utc(),
        "status": "running",
        "commands": [],
        "benchmarkScope": "durable-ledger-only-not-combined-Agentd-request-latency",
        "operatorAcceptance": "not_established",
        "promotion": "not_authorized",
    }
    receipt = evidence / "command-record.json"
    q.write_json(receipt, record)
    failure = q.identity_error(
        head, args.source_commit, args.source_commit, "", "source-head"
    )
    if failure or q.git("status", "--porcelain", "--untracked-files=all"):
        record.update(
            status="failed",
            failure=failure or "initial_worktree_dirty",
            worktreeUnchanged=False,
        )
        q.write_json(receipt, record)
        q.seal(evidence)
        return 1
    lock = q.ROOT / "codex-rs/Cargo.lock"
    record["cargoLockSha256"] = q.sha256(lock) if lock.is_file() else None
    failed = False
    for name, command in COMMANDS:
        row = {
            "name": name,
            "argv": command,
            "cwd": "codex-rs",
            "startedAt": q.utc(),
            "status": "running",
        }
        record["commands"].append(row)
        q.write_json(receipt, record)
        log = evidence / (name + ".log")
        start = time.monotonic()
        print(f"::group::{name}\n$ {' '.join(command)}", flush=True)
        code = q.execute(command, log, q.ROOT / "codex-rs", args.command_timeout)
        passed = code == 0
        if command[:2] == ["cargo", "test"]:
            row["nonzeroTests"] = q.nonzero_tests(log)
            passed = passed and row["nonzeroTests"]
        row.update(
            status="passed" if passed else "failed",
            exitCode=code,
            finishedAt=q.utc(),
            durationSeconds=round(time.monotonic() - start, 6),
            log=log.name,
            logSha256=q.sha256(log),
            logSummary=q.log_summary(log),
        )
        failed = failed or not passed
        q.write_json(receipt, record)
        print(row["logSummary"] + f"\nexit_code={code}\n::endgroup::", flush=True)
        if code == 130:
            break
    unchanged = (
        q.git("rev-parse", "HEAD") == head
        and q.git("rev-parse", "HEAD^{tree}") == tree
        and not q.git("status", "--porcelain", "--untracked-files=all")
    )
    record.update(
        status="passed" if not failed and unchanged else "failed",
        worktreeUnchanged=unchanged,
        finishedAt=q.utc(),
    )
    q.write_json(receipt, record)
    q.write_json(evidence / "ledger-report.json", record)
    q.seal(evidence)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
