#!/usr/bin/env python3
"""Read-only, exact-tree learning.eval qualification with failure-preserving receipts.

This proves only the commands actually run against one immutable checkout. It
never edits source/status, issues operator acceptance, or manufactures host data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any

SCHEMA = "hepta.learning-eval.exact-execution.v1"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def digest_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_checkout(
    root: Path,
    source: str,
    candidate: str,
    base: str | None,
    kind: str,
) -> dict[str, Any]:
    for value in [source, candidate] + ([base] if base else []):
        if not SHA_RE.fullmatch(value):
            raise ValueError("qualification requires full lowercase commit SHAs")
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("checkout does not match the requested exact commit")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked source is dirty")
    parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
    if kind == "merge":
        if base is None or parents != [base, candidate]:
            raise ValueError("merge must have ordered parents [exact base, exact candidate]")
    elif kind != "head" or source != candidate:
        raise ValueError("head qualification must test the exact candidate")
    return {
        "commit": source,
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "candidateCommit": candidate,
        "baseCommit": base,
        "kind": kind,
        "orderedParents": parents,
    }


def execute(
    name: str,
    argv: list[str],
    cwd: Path,
    output: Path,
    timeout: int = 3600,
) -> dict[str, Any]:
    """Record both success and failure; kill the process group on timeout."""
    started = utc_now()
    before = time.monotonic()
    log = output / f"{name}.log"
    status = "failed"
    code: int | None = None
    error: str | None = None
    with log.open("wb") as stream:
        stream.write((json.dumps({"argv": argv, "cwd": str(cwd)}) + "\n").encode())
        stream.flush()
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=timeout)
                status = "passed" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
                status = "timed_out"
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            stream.write((error + "\n").encode())
    return {
        "name": name,
        "argv": argv,
        "cwd": str(cwd),
        "startedAt": started,
        "finishedAt": utc_now(),
        "durationSeconds": round(time.monotonic() - before, 6),
        "status": status,
        "exitCode": code,
        "error": error,
        "log": {
            "path": log.name,
            "sha256": digest_file(log),
            "bytes": log.stat().st_size,
        },
    }


def commands(output: Path) -> list[tuple[str, list[str], str]]:
    packages = [
        "-p",
        "codex-hepta-intelligence-eval",
        "-p",
        "codex-hepta-intelligence",
        "-p",
        "codex-hepta-agentd",
    ]
    return [
        (
            "source-status",
            ["python3", "scripts/hepta-learning-eval-status.py", "verify"],
            ".",
        ),
        (
            "identifier-regressions",
            ["python3", "scripts/test_hepta_rust_identifiers.py"],
            ".",
        ),
        (
            "target-host-verifier-self-test",
            ["python3", "scripts/hepta-learning-eval-target-host.py", "self-test"],
            ".",
        ),
        ("api-surface", ["bash", "scripts/hepta-learning-eval-api-surface.sh"], "."),
        (
            "owner-consumer-compile",
            ["cargo", "check", "--locked", *packages, "--all-targets"],
            "codex-rs",
        ),
        (
            "owner-tests",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "signed-e2e",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "signed_qualification_e2e",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "shadow-consumer",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence",
                "evaluated_shadow",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "plasticity-consumer",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence",
                "plasticity_product",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "agentd-consumer",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "intelligence_evaluation_tests",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "agentd-outcome-consumer",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "multi_outcome_consumer_rejects_context_owner_and_signature_substitution",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "cold-recovery-e2e",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "--test",
                "cold_recovery_e2e",
                "--test-threads=1",
            ],
            "codex-rs",
        ),
        (
            "fault-matrix",
            [
                "bash",
                "scripts/hepta-learning-eval-faults.sh",
                "--json",
                str(output / "faults.json"),
                "--log",
                str(output / "faults.log"),
            ],
            ".",
        ),
        (
            "storage-profile",
            [
                "cargo",
                "run",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "--bin",
                "learning_eval_storage_profile",
                "--",
                "--attempts",
                "1024",
                "--fences",
                "512",
                "--output",
                str(output / "storage-profile.json"),
            ],
            "codex-rs",
        ),
        (
            "default-production-coverage",
            [
                "cargo",
                "llvm-cov",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "--all-targets",
                "--no-default-features",
                "--fail-under-lines",
                "85",
                "--json",
                "--output-path",
                str(output / "coverage.json"),
            ],
            "codex-rs",
        ),
        (
            "compatibility-coverage",
            [
                "cargo",
                "llvm-cov",
                "--locked",
                "-p",
                "codex-hepta-intelligence-eval",
                "--features",
                "trusted-inprocess-eval",
                "--test",
                "operator_claim",
                "--json",
                "--output-path",
                str(output / "compatibility-coverage.json"),
            ],
            "codex-rs",
        ),
        (
            "strict-lint",
            [
                "cargo",
                "clippy",
                "--locked",
                *packages,
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
            "codex-rs",
        ),
        (
            "format",
            [
                "cargo",
                "fmt",
                "--package",
                "codex-hepta-intelligence-eval",
                "--package",
                "codex-hepta-intelligence",
                "--package",
                "codex-hepta-agentd",
                "--",
                "--check",
            ],
            "codex-rs",
        ),
        ("diff-check", ["git", "diff", "--check"], "."),
    ]


def line_totals(path: Path) -> tuple[int, int, float]:
    totals = json.loads(path.read_text())["data"][0]["totals"]["lines"]
    count, covered = int(totals["count"]), int(totals["covered"])
    percent = float(totals["percent"])
    if count <= 0 or not 0 <= covered <= count:
        raise ValueError(f"invalid coverage totals: {path.name}")
    return count, covered, percent


def validate_outputs(output: Path) -> dict[str, Any]:
    count, covered, percent = line_totals(output / "coverage.json")
    if covered * 100 < count * 85:
        raise ValueError("default-production coverage is below 85 percent")
    compat_count, compat_covered, compat_percent = line_totals(
        output / "compatibility-coverage.json"
    )
    profile = json.loads((output / "storage-profile.json").read_text())
    if (
        profile["schema"] != "hepta.learning-eval.storage-profile.v1"
        or profile["attempts"]["attemptCount"] != 1024
        or profile["attempts"]["eventCount"] != 7168
        or profile["holdout"]["fenceTransitions"] != 512
        or profile["holdout"]["anchorPreserved"] is not True
        or profile["holdout"]["afterBytes"] >= profile["holdout"]["beforeBytes"]
    ):
        raise ValueError("storage profile does not satisfy the preregistered source profile")
    return {
        "defaultProductionCoverage": {
            "count": count,
            "covered": covered,
            "percent": percent,
            "thresholdPct": 85,
        },
        "compatibilityCoverage": {
            "count": compat_count,
            "covered": compat_covered,
            "percent": compat_percent,
            "gating": False,
        },
        "storageProfileScope": (
            "synthetic single-host source profile; not target-host acceptance"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--base-commit")
    parser.add_argument("--kind", choices=["head", "merge"], required=True)
    args = parser.parse_args(argv)
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    output = root / ".hepta-evidence" / "learning-eval" / args.kind
    # Evidence is the only write destination. Do not follow a redirected directory.
    if any(path.is_symlink() for path in [output, output.parent, output.parent.parent]):
        parser.error("evidence directory must not be a symlink")
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "startedAt": utc_now(),
        "source": None,
        "commands": [],
        "build": {
            key: os.environ.get(key)
            for key in [
                "GITHUB_REPOSITORY",
                "GITHUB_WORKFLOW",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "RUNNER_OS",
                "RUNNER_ARCH",
            ]
        },
        "authority": "DENY_ALL",
        "claims": {
            "sourceQualifiedByThisRun": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
        "errors": [],
    }
    try:
        manifest["source"] = validate_checkout(
            root,
            args.source_commit,
            args.candidate_commit,
            args.base_commit,
            args.kind,
        )
        failed = False
        for name, command, directory in commands(output):
            if failed:
                manifest["commands"].append(
                    {
                        "name": name,
                        "argv": command,
                        "status": "not_run_after_failure",
                        "exitCode": None,
                    }
                )
                continue
            result = execute(name, command, root / directory, output)
            manifest["commands"].append(result)
            print(
                f"{name}: {result['status']} (exit={result['exitCode']})",
                flush=True,
            )
            failed = result["status"] != "passed"
        if not failed:
            manifest["measurements"] = validate_outputs(output)
        after = validate_checkout(
            root,
            args.source_commit,
            args.candidate_commit,
            args.base_commit,
            args.kind,
        )
        if after != manifest["source"]:
            raise ValueError("source identity changed during qualification")
        manifest["trackedSourceUnchanged"] = True
        manifest["claims"]["sourceQualifiedByThisRun"] = not failed
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as exc:
        manifest["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        manifest["finishedAt"] = utc_now()
        manifest["outputs"] = {
            path.name: {
                "sha256": digest_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.iterdir())
            if path.is_file()
        }
        path = output / "convergence.json"
        path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(path, flush=True)
    return 0 if manifest["claims"]["sourceQualifiedByThisRun"] else 1


if __name__ == "__main__":
    sys.exit(main())
