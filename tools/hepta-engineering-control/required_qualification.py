#!/usr/bin/env python3
"""Read-only exact-candidate qualification for ``control.engineering``.

The runner is shared by pull-request source/base-merge lanes and protected-main
post-merge qualification. It records every command and produces reference CI
receipts, but grants no merge, runtime, deployment, promotion, release, or
independent-acceptance authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Sequence

PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT / "control_engineering_v2"
NEW_MODULES = (
    SOURCE_ROOT / "audit_checkpoint.py",
    SOURCE_ROOT / "capacity_policy.py",
    SOURCE_ROOT / "clock_policy.py",
    SOURCE_ROOT / "durability_soak.py",
    SOURCE_ROOT / "external_runtime.py",
    SOURCE_ROOT / "quality_gate.py",
    SOURCE_ROOT / "release_qualification.py",
    SOURCE_ROOT / "status.py",
    SOURCE_ROOT / "worker_registration_governance.py",
)
LINT_TARGETS = NEW_MODULES + (
    PACKAGE_ROOT / "quality_campaign.py",
    PACKAGE_ROOT / "required_qualification.py",
    PACKAGE_ROOT / "test_governance_convergence.py",
    PACKAGE_ROOT / "test_external_release_convergence.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )
    if result.returncode != 0:
        raise RuntimeError(f"git command failed: {args!r}: {result.stderr[-2000:]}")
    return result.stdout.strip()


def _run(
    name: str,
    argv: Sequence[str],
    *,
    repository: Path,
    output: Path,
    environment: dict[str, str] | None = None,
    timeout: int = 1_800,
) -> None:
    log = output / f"{name}.log"
    record = output / f"{name}.command.json"
    started = time.time_ns()
    env = dict(os.environ)
    if environment:
        env.update(environment)
    with log.open("wb") as handle:
        try:
            result = subprocess.run(
                list(argv),
                cwd=repository,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            exit_code = int(result.returncode)
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code = 124
            timed_out = True
    completed = time.time_ns()
    body = {
        "schema": "hepta.control-engineering-command.v1",
        "name": name,
        "argv": list(argv),
        "startedUnixNs": started,
        "completedUnixNs": completed,
        "durationMillis": round((completed - started) / 1_000_000, 3),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "logBytes": log.stat().st_size,
        "logSha256": _sha256(log),
    }
    record.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if exit_code != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-12_000:]
        raise RuntimeError(f"{name} failed with exit code {exit_code}:\n{tail}")


def _unit_test_count(log: Path) -> int:
    value = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Ran (\d+) tests?", value)
    if match is None:
        raise RuntimeError("unit test count missing")
    return int(match.group(1))


def _write_soak(output: Path, source_commit: str, source_tree: str) -> None:
    from control_engineering_v2.control_plane import (
        DENIED_AUTHORITIES,
        EngineeringStore,
        WorkEnvelope,
    )
    from control_engineering_v2.durability_soak import run_durability_soak

    database = output / "soak.sqlite3"
    with EngineeringStore(database) as store:
        store.issue_work_envelope(
            WorkEnvelope(
                "blocking-ci-soak",
                source_commit,
                source_tree,
                "a" * 64,
                "b" * 64,
                "developer-productivity",
                ("tools/hepta-engineering-control",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                10_000_000_000_000_000_000,
            ),
            now_ns=1_000_000,
        )
    report = run_durability_soak(database, iterations=50)
    (output / "durability-soak.json").write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_quality_receipt(
    output: Path,
    *,
    repository_name: str,
    source_commit: str,
    source_tree: str,
) -> str:
    from control_engineering_v2.evidence import HmacTrustStore
    from control_engineering_v2.quality_gate import (
        QualityGatePolicy,
        QualityGateReceipt,
        verify_quality_gate,
    )

    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))["totals"]
    campaign = json.loads(
        (output / "quality-campaign.json").read_text(encoding="utf-8")
    )
    soak = json.loads((output / "durability-soak.json").read_text(encoding="utf-8"))
    statements = int(coverage["num_statements"])
    branches = int(coverage.get("num_branches", 0))
    if statements < 1 or branches < 1:
        raise RuntimeError("coverage totals are incomplete")
    now = time.time_ns()
    receipt = QualityGateReceipt(
        repository_name,
        source_commit,
        source_tree,
        _unit_test_count(output / "unit-tests.log"),
        int(coverage["covered_lines"]) * 65_536 // statements,
        int(coverage.get("covered_branches", 0)) * 65_536 // branches,
        int(campaign["mutation"]["scoreQ16"]),
        int(soak["iterations"]),
        _sha256(output / "unit-tests.log"),
        _sha256(output / "coverage.json"),
        _sha256(output / "mypy.log"),
        _sha256(output / "ruff.log"),
        _sha256(output / "quality-campaign.json"),
        _sha256(output / "quality-campaign.json"),
        _sha256(output / "durability-soak.json"),
        "ci_executor",
        "github-actions-reference-v1",
        now,
        now + 3_600_000_000_000,
    )
    trust = HmacTrustStore(
        {
            ("ci_executor", "github-actions-reference-v1"):
                b"hepta-control-quality-reference-v1"
        }
    )
    receipt = replace(
        receipt,
        signature=trust.sign(receipt, receipt.issuer, receipt.signing_identity),
    )
    decision = verify_quality_gate(
        receipt,
        trust,
        expected_repository=repository_name,
        expected_source_commit=source_commit,
        expected_source_tree=source_tree,
        policy=QualityGatePolicy(
            minimum_line_coverage_q16=52_429,
            minimum_branch_coverage_q16=45_875,
            minimum_mutation_score_q16=65_536,
            minimum_test_count=1,
            minimum_soak_iterations=50,
        ),
        now_ns=now,
    )
    if not decision.qualified:
        raise RuntimeError("quality gate blocked: " + ",".join(decision.blockers))
    (output / "quality-receipt.json").write_text(
        json.dumps(
            {"receipt": asdict(receipt), "decision": asdict(decision)},
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return decision.receipt_digest


def _write_post_merge_receipt(
    output: Path,
    *,
    repository_name: str,
    source_commit: str,
    source_tree: str,
    run_id: int,
    quality_digest: str,
) -> None:
    from control_engineering_v2.evidence import HmacTrustStore
    from control_engineering_v2.release_qualification import PostMergeMainReceipt

    now = time.time_ns()
    receipt = PostMergeMainReceipt(
        repository_name,
        source_commit,
        source_tree,
        "main",
        run_id,
        _sha256(output / "product-receipt.json"),
        _sha256(output / "unit-tests.log"),
        _sha256(output / "host-profile.json"),
        quality_digest,
        "ci_executor",
        "github-actions-reference-v1",
        now,
        now + 3_600_000_000_000,
    )
    trust = HmacTrustStore(
        {
            ("ci_executor", "github-actions-reference-v1"):
                b"hepta-control-quality-reference-v1"
        }
    )
    receipt = replace(
        receipt,
        signature=trust.sign(receipt, receipt.issuer, receipt.signing_identity),
    )
    if not trust.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise RuntimeError("post-merge receipt signature verification failed")
    (output / "post-merge-main-receipt.json").write_text(
        json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--repository-full-name", required=True)
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--lane", choices=("source-head", "base-merge"), required=True)
    parser.add_argument("--pull-request-number", required=True, type=int)
    parser.add_argument("--quality-python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--post-merge-main", action="store_true")
    args = parser.parse_args(argv)

    repository = args.repository.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tested_sha = _git(repository, "rev-parse", "HEAD")
    tested_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    if args.lane == "source-head" and tested_sha != args.source_sha:
        raise RuntimeError("source-head identity mismatch")
    if _git(repository, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("qualification repository is not clean")

    pythonpath = str(PACKAGE_ROOT)
    shared_environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": pythonpath,
        "SOURCE_SHA": args.source_sha,
        "BASE_SHA": args.base_sha,
        "TESTED_SHA": tested_sha,
        "TESTED_TREE": tested_tree,
        "HEPTA_CI_LANE": args.lane,
    }
    _run(
        "gap-closure",
        [sys.executable, "scripts/hepta-gap-closure.py", "verify"],
        repository=repository,
        output=output,
        environment=shared_environment,
    )
    coverage_file = output / ".coverage"
    test_environment = {
        **shared_environment,
        "HEPTA_REQUIRE_STRONG_SANDBOX": "1",
        "COVERAGE_FILE": str(coverage_file),
    }
    _run(
        "unit-tests",
        [
            str(args.quality_python),
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=tools/hepta-engineering-control/control_engineering_v2",
            "-m",
            "unittest",
            "discover",
            "-v",
            "-s",
            "tools/hepta-engineering-control",
            "-p",
            "test_*.py",
        ],
        repository=repository,
        output=output,
        environment=test_environment,
        timeout=1_800,
    )
    _run(
        "coverage-json",
        [
            str(args.quality_python),
            "-m",
            "coverage",
            "json",
            "-o",
            str(output / "coverage.json"),
        ],
        repository=repository,
        output=output,
        environment=test_environment,
    )
    _run(
        "coverage-report",
        [str(args.quality_python), "-m", "coverage", "report", "--fail-under=80"],
        repository=repository,
        output=output,
        environment=test_environment,
    )
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))["totals"]
    if (
        int(coverage.get("num_branches", 0)) < 1
        or int(coverage.get("covered_branches", 0)) * 100
        < int(coverage["num_branches"]) * 70
    ):
        raise RuntimeError("branch coverage below 70%")

    _run(
        "mypy",
        [
            str(args.quality_python),
            "-m",
            "mypy",
            "--python-version",
            "3.12",
            "--follow-imports=skip",
            "--ignore-missing-imports",
            "--check-untyped-defs",
            "--warn-unused-ignores",
            "--show-error-codes",
            *(str(path.relative_to(repository)) for path in NEW_MODULES),
        ],
        repository=repository,
        output=output,
        environment=shared_environment,
    )
    _run(
        "ruff",
        [
            str(args.quality_python),
            "-m",
            "ruff",
            "check",
            "--output-format=github",
            *(str(path.relative_to(repository)) for path in LINT_TARGETS),
        ],
        repository=repository,
        output=output,
        environment=shared_environment,
    )
    _run(
        "quality-campaign",
        [
            sys.executable,
            str(PACKAGE_ROOT / "quality_campaign.py"),
            "all",
            "--root",
            str(PACKAGE_ROOT),
            "--api-snapshot",
            str(PACKAGE_ROOT / "QUALITY_API.json"),
            "--output",
            str(output / "quality-campaign.json"),
        ],
        repository=repository,
        output=output,
        environment=shared_environment,
        timeout=1_800,
    )
    _write_soak(output, tested_sha, tested_tree)
    _run(
        "host-profile",
        [
            sys.executable,
            "-m",
            "control_engineering_v2.qualification_profile",
            "--repository",
            str(repository),
            "--iterations",
            "7",
            "--sandbox-mode",
            "strong",
            "--output",
            str(output / "host-profile.json"),
        ],
        repository=repository,
        output=output,
        environment=shared_environment,
        timeout=1_800,
    )
    quality_digest = _write_quality_receipt(
        output,
        repository_name=args.repository_full_name,
        source_commit=tested_sha,
        source_tree=tested_tree,
    )
    _run(
        "product-gate",
        [
            sys.executable,
            "-m",
            "control_engineering_v2.product_gate",
            "--repository",
            str(repository),
            "--repository-full-name",
            args.repository_full_name,
            "--repository-id",
            str(args.repository_id),
            "--workflow-ref",
            args.workflow_ref,
            "--job-name",
            args.job_name,
            "--run-id",
            str(args.run_id),
            "--run-attempt",
            str(args.run_attempt),
            "--source-sha",
            args.source_sha,
            "--base-sha",
            args.base_sha,
            "--event-name",
            args.event_name,
            "--lane",
            args.lane,
            "--pull-request-number",
            str(args.pull_request_number),
            "--output",
            str(output / "product-receipt.json"),
        ],
        repository=repository,
        output=output,
        environment=shared_environment,
        timeout=1_800,
    )
    if args.post_merge_main:
        if args.event_name != "push" or args.lane != "source-head":
            raise RuntimeError("post-merge main receipt requires a source-head push")
        _write_post_merge_receipt(
            output,
            repository_name=args.repository_full_name,
            source_commit=tested_sha,
            source_tree=tested_tree,
            run_id=args.run_id,
            quality_digest=quality_digest,
        )
    summary = {
        "schema": "hepta.control-engineering-required-qualification.v1",
        "repository": args.repository_full_name,
        "sourceSha": args.source_sha,
        "testedSha": tested_sha,
        "testedTree": tested_tree,
        "baseSha": args.base_sha,
        "lane": args.lane,
        "qualityReceiptDigest": quality_digest,
        "postMergeMain": args.post_merge_main,
        "authority": {
            "runtime": False,
            "merge": False,
            "deployment": False,
            "promotion": False,
            "release": False,
        },
    }
    (output / "qualification-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
