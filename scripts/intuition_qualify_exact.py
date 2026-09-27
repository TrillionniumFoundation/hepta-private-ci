#!/usr/bin/env python3
"""Read-only intuition qualification; never format, migrate, commit or sign acceptance.

Receipts live outside the checkout. A planned command is never recorded as passed.
The checked-out tree, PR source and base remain distinct, including merge runs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ["-p", "codex-hepta-intuition", "-p", "codex-hepta-intelligence", "-p", "codex-hepta-agentd"]
COMMANDS = [
    ("fmt", ["cargo", "fmt", *PACKAGES, "--", "--check"]),
    ("check", ["cargo", "check", "--locked", *PACKAGES, "--all-targets"]),
    ("clippy", ["cargo", "clippy", "--locked", *PACKAGES, "--all-targets", "--", "-D", "warnings"]),
    ("policy-tests", ["cargo", "test", "--locked", "-p", "codex-hepta-intuition"]),
    ("qualification-tests", ["cargo", "test", "--locked", "-p", "codex-hepta-intelligence"]),
    ("agentd-policy-tests", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "--lib", "intuition_policy"]),
    ("agentd-product-tests", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "--test", "intuition_policy_product"]),
    ("agentd-v3-product-tests", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "--test", "intuition_policy_product_v3"]),
    ("kernel-fast-gate", ["cargo", "run", "--locked", "--release", "-p", "codex-hepta-intuition", "--example", "fast_gate"]),
    ("authenticated-fast-gate", ["cargo", "run", "--locked", "--release", "-p", "codex-hepta-intelligence", "--example", "intuition_authenticated_fast_gate"]),
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--lane", choices=["source-head", "synthetic-merge"], required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if evidence == ROOT or ROOT in evidence.parents:
        parser.error("evidence must be outside the tested checkout")
    evidence.mkdir(parents=True, exist_ok=True)
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    record = {
        "schema": "hepta.intuition.exact-command-record.v2",
        "sourceSha": args.source_sha,
        "baseSha": args.base_sha or None,
        "testedSha": head,
        "testedTree": tree,
        "lane": args.lane,
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "host": platform.platform(),
        "startedAt": utc(),
        "status": "running",
        "commands": [],
        "independentAcceptance": "not_established",
        "operatorAcceptance": "not_established",
        "promotion": "not_authorized",
    }
    receipt = evidence / "command-record.json"
    write_json(receipt, record)
    initial = git("status", "--porcelain", "--untracked-files=all")
    if head != args.expected_sha or initial:
        record.update(status="failed", failure="source_identity_or_initial_worktree", worktree=initial)
        write_json(receipt, record)
        return 1
    toolchain = evidence / "toolchain.txt"
    with toolchain.open("w", encoding="utf-8") as stream:
        for command in (["rustc", "-Vv"], ["cargo", "-V"], ["uname", "-a"]):
            stream.write("$ " + " ".join(command) + "\n")
            stream.flush()
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
    failed = False
    for name, command in COMMANDS:
        result = {"name": name, "argv": command, "cwd": "codex-rs", "startedAt": utc(), "status": "running"}
        record["commands"].append(result)
        write_json(receipt, record)
        start = time.monotonic()
        log = evidence / (name + ".log")
        print("::group::" + name, flush=True)
        print("$ " + " ".join(command), flush=True)
        try:
            with log.open("wb") as stream:
                completed = subprocess.run(command, cwd=ROOT / "codex-rs", stdout=stream, stderr=subprocess.STDOUT, check=False)
            code = completed.returncode
        except OSError as error:
            log.write_text(str(error) + "\n", encoding="utf-8")
            code = 127
        result.update(exitCode=code, status="passed" if code == 0 else "failed", finishedAt=utc(), durationSeconds=round(time.monotonic() - start, 6), logSha256=hashlib.sha256(log.read_bytes()).hexdigest())
        failed = failed or code != 0
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]), flush=True)
        print("exit_code=" + str(code), flush=True)
        print("::endgroup::", flush=True)
        write_json(receipt, record)
    final = git("status", "--porcelain", "--untracked-files=all")
    unchanged = git("rev-parse", "HEAD") == head and git("rev-parse", "HEAD^{tree}") == tree and not final
    record.update(status="passed" if not failed and unchanged else "failed", finishedAt=utc(), worktreeUnchanged=unchanged, finalWorktree=final)
    write_json(receipt, record)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
