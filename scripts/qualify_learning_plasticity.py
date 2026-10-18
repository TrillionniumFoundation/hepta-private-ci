#!/usr/bin/env python3
"""Read-only, exact-candidate learning.plasticity qualification.

The runner never refreshes documents, reconstructs source, applies patches, commits or
pushes. Every independent gate executes and its result is preserved in one lane
receipt. Production/target-host claims remain false even when repository gates pass.
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
from typing import Any


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def rust_host() -> str | None:
    value = command_output(["rustc", "-vV"])
    if value is None:
        return None
    for line in value.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ")
    return None


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
    lane = os.environ.get("LANE", "source-head")
    if lane not in {"source-head", "synthetic-merge", "final-merge"}:
        parser.error(f"unsupported lane: {lane}")
    if git("rev-parse", "HEAD") != tested or git("status", "--porcelain"):
        raise RuntimeError("candidate is not the exact clean tested commit")

    packages = [
        "codex-hepta-plasticity",
        "codex-hepta-learning-artifacts",
        "codex-hepta-intelligence",
        "codex-hepta-agentd",
        "codex-hepta-runtime",
    ]
    check_flags = [item for package in packages for item in ("-p", package)]
    fmt_flags = [item for package in packages for item in ("--package", package)]
    mapping_path = output / "exact-mapping.json"

    commands: list[tuple[str, Path, list[str]]] = [
        (
            "single-source-contract",
            root,
            [
                "python3",
                "scripts/verify_learning_plasticity_exact_mapping.py",
                "--output",
                str(mapping_path),
            ],
        ),
        (
            "grammar-contract",
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
            ["cargo", "check", "--locked", "--all-targets", *check_flags],
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
            "agentd-plasticity",
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
            [
                "cargo",
                "clippy",
                "--locked",
                "--all-targets",
                *check_flags,
                "--",
                "-D",
                "warnings",
            ],
        ),
        ("diff-check", root, ["git", "diff", "--check"]),
        ("unchanged-tree", root, ["git", "diff", "--exit-code"]),
    ]

    receipt: dict[str, Any] = {
        "schema": "hepta.learning-plasticity-exact-execution.v3",
        "module": "learning.plasticity",
        "sourceCommit": source,
        "sourceTree": git("rev-parse", f"{source}^{{tree}}"),
        "baseCommit": base,
        "baseTree": git("rev-parse", f"{base}^{{tree}}"),
        "testedCommit": tested,
        "testedTree": git("rev-parse", "HEAD^{tree}"),
        "lane": lane,
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerImage": os.environ.get("ImageOS"),
        "runnerImageVersion": os.environ.get("ImageVersion"),
        "targetTriple": rust_host(),
        "platform": platform.platform(),
        "cargoLockSha256": sha256(root / "codex-rs/Cargo.lock"),
        "implementationMapSha256": sha256(
            root / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
        ),
        "exactMappingOverlaySha256": sha256(
            root / "docs/modules/learning.plasticity/EXACT_MAPPING.json"
        ),
        "startedAtUnixSeconds": int(time.time()),
        "targetHostEvidence": False,
        "rollbackDomainIndependenceProved": False,
        "independentAcceptance": False,
        "operatorAcceptance": False,
        "activation": False,
        "release": False,
        "productionQualified": False,
        "mergeReady": False,
        "commands": [],
        "repositoryChecksPassed": False,
    }
    receipt_path = output / "execution.json"
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
                "durationSeconds": round(time.monotonic() - started, 6),
                "logSha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")

    candidate_unchanged = (
        git("rev-parse", "HEAD") == tested
        and not git("status", "--porcelain", "--untracked-files=no")
    )
    passed = candidate_unchanged and all(
        row["exitCode"] == 0 for row in receipt["commands"]
    )
    receipt["candidateUnchanged"] = candidate_unchanged
    receipt["repositoryChecksPassed"] = passed
    receipt["mergeReady"] = passed
    receipt["productionQualified"] = False
    receipt["finishedAtUnixSeconds"] = int(time.time())
    if mapping_path.is_file():
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        receipt["testInventorySha256"] = mapping.get("testInventorySha256")
        receipt["documentationSha256"] = mapping.get("documentationSha256")
        receipt["exactMappingReceiptSha256"] = sha256(mapping_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
