#!/usr/bin/env python3
"""Bind knowledge.graph delivery contracts to exact execution evidence.

This validates execution artifacts only. It never promotes production,
independent acceptance, activation or release state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
SUMMARY = re.compile(
    r"test result: ok\. ([0-9]+) passed; 0 failed; ([0-9]+) ignored;",
    re.MULTILINE,
)
OPERATION_PREFIX = "HEPTA_KG_OPERATION_METRICS="

COMMON_CHECKS = (
    "execution-audit-tests",
    "measurement-tests",
    "budget-tests",
    "measurement-self-test",
    "implementation-maps",
    "formatting",
)
KERNEL_CHECKS = ("kg-kernel", "kg-clippy")
PRODUCT_CHECKS = (
    "prompt-registry",
    "prompt-optimizer",
    "cognitive-owner",
    "delivery-consistency",
    "crash-reopen",
    "history-reopen",
    "agentd-default",
    "agentd-witness",
    "strict-clippy",
)
QUERY_TESTS = (
    "indexed_receipts_equal_reference_across_time_filters_seeds_and_bounds",
    "work_budget_boundary_is_exact_and_no_partial_success_is_returned",
    "view_cannot_satisfy_another_source_cut_or_a_changed_generation_digest",
    "external_budget_distinguishes_empty_exhausted_invalid_and_unbounded",
)
RECOVERY_TESTS = (
    "source_acknowledgement_retry_survives_wal_reader_and_reopen",
    "competing_memory_corrections_rollback_the_losing_source",
    "projection_failure_rolls_back_source_memory_and_facts_before_reopen",
)
DELIVERY_TESTS = (
    "committed_unknown_result_reconciles_exact_receipt_after_reopen",
    "competing_head_reopen_selects_one_complete_receipt",
)


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_KG_DELIVERY_EVIDENCE: " + message)


def strict_object(text: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("root must be an object")
    return value


def read_results(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0] or not fields[1].isdigit():
            fail(f"invalid result row: {line!r}")
        name, status = fields[0], int(fields[1])
        if name in result:
            fail(f"duplicate result row: {name}")
        result[name] = status
    return result


def require_checks(results: dict[str, int], names: tuple[str, ...]) -> None:
    missing = [name for name in names if name not in results]
    failed = [name for name in names if results.get(name, 1) != 0]
    if missing:
        fail("missing checks: " + ", ".join(missing))
    if failed:
        fail("failed checks: " + ", ".join(failed))


def require_identity(
    path: Path,
    source_sha: str,
    base_sha: str,
    tested_sha: str,
    tested_tree: str,
) -> None:
    expected = [
        f"source={source_sha}",
        f"base={base_sha}",
        tested_sha,
        tested_tree,
    ]
    observed = path.read_text(encoding="utf-8").splitlines()
    if observed != expected:
        fail("identity.txt does not bind the selected source/base/tested commit/tree")


def require_test_names(log: Path, names: tuple[str, ...]) -> None:
    text = log.read_text(encoding="utf-8", errors="replace")
    missing = [name for name in names if name not in text]
    if missing:
        fail(f"{log.name} does not prove tests: {', '.join(missing)}")


def require_exact_test_summary(
    log: Path,
    *,
    passed: int,
    ignored: int = 0,
) -> None:
    text = log.read_text(encoding="utf-8", errors="replace")
    summaries = [(int(run), int(skip)) for run, skip in SUMMARY.findall(text)]
    if summaries != [(passed, ignored)]:
        fail(
            f"{log.name} must contain exactly one successful summary with "
            f"{passed} passed and {ignored} ignored"
        )


def parse_operation_metrics(log: Path) -> dict[str, Any]:
    text = log.read_text(encoding="utf-8", errors="replace")
    summaries = [(int(run), int(skip)) for run, skip in SUMMARY.findall(text)]
    if summaries != [(1, 0)]:
        fail("operation-metrics.log does not prove one executed measurement test")
    rows = [
        line.split(OPERATION_PREFIX, 1)[1]
        for line in text.splitlines()
        if OPERATION_PREFIX in line
    ]
    if len(rows) != 1:
        fail(f"expected one operation metric receipt, got {len(rows)}")
    try:
        metrics = strict_object(rows[0])
    except (ValueError, json.JSONDecodeError) as error:
        fail(f"invalid operation metric receipt: {error}")
    if metrics.get("schema") != "hepta.knowledge-graph-operation-metrics.v2":
        fail("unexpected operation metric schema")
    timings = (
        "inputCloneNs",
        "buildValidateSealNs",
        "generationUpdateNs",
        "verifiedViewBuildNs",
        "coldBoundedQueryNs",
        "hotBoundedQueryTotalNs",
        "unboundedReferenceQueryNs",
        "publicationReceiptNs",
        "iterations",
        "defaultSupportWork",
        "maximumSupportWork",
    )
    for field in timings:
        value = metrics.get(field)
        if type(value) is not int or value <= 0:
            fail(f"invalid operation metric {field}")
    if metrics["defaultSupportWork"] > metrics["maximumSupportWork"]:
        fail("default support-work budget exceeds the library maximum")
    return metrics


def distribution(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        fail(f"missing distribution: {field}")
    result: dict[str, int] = {}
    previous = -1
    for key in ("p50", "p95", "p99"):
        current = value.get(key)
        if type(current) is not int or current < 0 or current < previous:
            fail(f"invalid distribution: {field}.{key}")
        result[key] = current
        previous = current
    return result


def parse_release_measurement(path: Path) -> dict[str, Any]:
    document = strict_object(path.read_text(encoding="utf-8"))
    benchmark = document.get("benchmark")
    if not isinstance(benchmark, dict):
        fail("release measurement lacks benchmark")
    phases = {
        "durableMutation": distribution(benchmark.get("mutationNs"), "mutationNs"),
        "hotQuery": distribution(benchmark.get("queryNs"), "queryNs"),
        "recoveryReopen": distribution(benchmark.get("reopenNs"), "reopenNs"),
    }
    contention = benchmark.get("contention")
    if not isinstance(contention, dict):
        fail("release measurement lacks contention")
    phases["contentionWriter"] = distribution(
        contention.get("writerNs"), "contention.writerNs"
    )
    phases["contentionReader"] = distribution(
        contention.get("readerNs"), "contention.readerNs"
    )
    phases["contentionRound"] = distribution(
        contention.get("roundNs"), "contention.roundNs"
    )
    if not isinstance(benchmark.get("boundedQueryWork"), dict):
        fail("release measurement lacks boundedQueryWork")
    return {
        "hostProfileId": document.get("hostProfileId"),
        "sourceCommit": document.get("sourceCommit"),
        "sourceTree": document.get("sourceTree"),
        "phases": phases,
        "boundedQueryWork": benchmark["boundedQueryWork"],
    }


def command_version(*command: str) -> str | None:
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def environment(profile: str, evidence: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "runnerOs": platform.system(),
        "runnerMachine": platform.machine(),
        "python": platform.python_version(),
        "rustc": command_version("rustc", "--version"),
        "cargo": command_version("cargo", "--version"),
        "protoc": command_version("protoc", "--version"),
        "runnerOsLabel": os.environ.get("RUNNER_OS"),
        "runnerArchLabel": os.environ.get("RUNNER_ARCH"),
        "runnerImageOs": os.environ.get("ImageOS"),
        "runnerImageVersion": os.environ.get("ImageVersion"),
        "githubRunId": os.environ.get("GITHUB_RUN_ID"),
        "githubJob": os.environ.get("GITHUB_JOB"),
    }
    if not result["rustc"] or not result["cargo"]:
        fail("Rust toolchain identity is unavailable")
    if profile == "product":
        recorded = (evidence / "protoc-version.txt").read_text(
            encoding="utf-8"
        ).strip()
        if not result["protoc"] or result["protoc"] != recorded:
            fail("live protoc identity differs from the recorded prerequisite")
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["environmentId"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return result


def file_receipt(path: Path, root: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(root)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def contract(
    name: str,
    symbol: str,
    tests: list[str],
    evidence: list[str],
    tested_sha: str,
    tested_tree: str,
    environment_id: str,
) -> dict[str, Any]:
    return {
        "contract": name,
        "implementationSymbol": symbol,
        "tests": tests,
        "testedCommit": tested_sha,
        "testedTree": tested_tree,
        "environmentId": environment_id,
        "evidence": evidence,
        "state": "scenario_executed",
        "openReason": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--profile", choices=("kernel", "product"), required=True)
    parser.add_argument("--lane", choices=("source-head", "base-merge"), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--tested-tree", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for label, value in (
        ("source", args.source_sha),
        ("base", args.base_sha),
        ("tested", args.tested_sha),
        ("tree", args.tested_tree),
    ):
        if SHA.fullmatch(value) is None:
            fail(f"{label} identity must be an exact SHA")

    evidence = args.evidence.resolve()
    require_identity(
        evidence / "identity.txt",
        args.source_sha,
        args.base_sha,
        args.tested_sha,
        args.tested_tree,
    )
    results = read_results(evidence / "results.tsv")
    required = COMMON_CHECKS + (
        KERNEL_CHECKS if args.profile == "kernel" else PRODUCT_CHECKS
    )
    if args.profile == "product" and args.lane == "source-head":
        required += ("release-measurement", "hosted-budget")
    require_checks(results, required)

    operation_metrics = parse_operation_metrics(evidence / "operation-metrics.log")
    observed_environment = environment(args.profile, evidence)
    environment_id = observed_environment["environmentId"]
    contracts: list[dict[str, Any]] = []
    evidence_names = {"identity.txt", "results.tsv", "operation-metrics.log"}

    if args.profile == "kernel":
        require_test_names(evidence / "kg-kernel.log", QUERY_TESTS)
        evidence_names.add("kg-kernel.log")
        contracts.extend(
            [
                contract(
                    "bounded external query has explicit default/maximum budgets and exact failure classification",
                    "VerifiedKnowledgeGenerationV2::query_relations_external",
                    list(QUERY_TESTS),
                    ["kg-kernel.log", "operation-metrics.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
                contract(
                    "unbounded full-scan query is an explicit oracle-only operation",
                    "query_relations_reference_unbounded",
                    ["external_budget_distinguishes_empty_exhausted_invalid_and_unbounded"],
                    ["kg-kernel.log", "operation-metrics.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
            ]
        )
    else:
        require_test_names(evidence / "cognitive-owner.log", RECOVERY_TESTS)
        require_test_names(evidence / "delivery-consistency.log", DELIVERY_TESTS)
        require_exact_test_summary(
            evidence / "delivery-consistency.log",
            passed=len(DELIVERY_TESTS),
        )
        require_exact_test_summary(evidence / "crash-reopen.log", passed=1)
        require_exact_test_summary(evidence / "history-reopen.log", passed=1)
        evidence_names.update(
            {
                "cognitive-owner.log",
                "delivery-consistency.log",
                "crash-reopen.log",
                "history-reopen.log",
                "protoc-version.txt",
            }
        )
        contracts.extend(
            [
                contract(
                    "lost acknowledgement retry reconciles the exact committed write receipt after reopen",
                    "CognitiveStore::correct_with_kg",
                    [DELIVERY_TESTS[0], RECOVERY_TESTS[0]],
                    ["delivery-consistency.log", "cognitive-owner.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
                contract(
                    "competing publication selects one complete head and rolls back the loser",
                    "CognitiveStore::correct_with_kg",
                    [DELIVERY_TESTS[1], RECOVERY_TESTS[1]],
                    ["delivery-consistency.log", "cognitive-owner.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
                contract(
                    "pre-publication failure leaves the exact predecessor",
                    "CognitiveStore::remember_with_kg",
                    [RECOVERY_TESTS[2]],
                    ["cognitive-owner.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
                contract(
                    "SIGKILL at both semantic-receipt/current-pointer windows restores predecessor",
                    "qualification_kg_projection_crash_windows_restore_exact_predecessor",
                    [
                        "before_semantic_receipt",
                        "after_semantic_receipt_before_current_pointer",
                    ],
                    ["crash-reopen.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
                contract(
                    "history deletion cannot resurrect across reopen",
                    "qualification_kg_history_reopen_no_resurrection",
                    ["qualification_kg_history_reopen_no_resurrection"],
                    ["history-reopen.log"],
                    args.tested_sha,
                    args.tested_tree,
                    environment_id,
                ),
            ]
        )

    release: dict[str, Any] | None = None
    if args.profile == "product" and args.lane == "source-head":
        release = parse_release_measurement(evidence / "release-measurement.json")
        if release["sourceCommit"] != args.tested_sha:
            fail("release measurement source commit mismatch")
        if release["sourceTree"] != args.tested_tree:
            fail("release measurement source tree mismatch")
        evidence_names.update(
            {
                "release-measurement.json",
                "release-native.log",
                "hosted-budget.json",
                "hosted-budget-result.json",
            }
        )

    evidence_files = [
        file_receipt(evidence / name, evidence)
        for name in sorted(evidence_names)
    ]
    document = {
        "schema": "hepta.knowledge-graph-delivery-evidence.v2",
        "sourceCommit": args.source_sha,
        "baseCommit": args.base_sha,
        "testedCommit": args.tested_sha,
        "testedTree": args.tested_tree,
        "profile": args.profile,
        "lane": args.lane,
        "environment": observed_environment,
        "contracts": contracts,
        "evidenceFiles": evidence_files,
        "operationMetrics": operation_metrics,
        "releaseMeasurement": release,
        "claimBoundary": {
            "sourceChecksPassed": True,
            "nativeBinaryCompiled": True,
            "queryScenarioExecuted": args.profile == "kernel",
            "recoveryScenarioExecuted": args.profile == "product",
            "destructiveScenarioExecuted": args.profile == "product",
            "historyScenarioExecuted": args.profile == "product",
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "openReasons": [
            "Hosted runner measurements are regression evidence, not operator target-host qualification.",
            "The public complete builder combines build, validation and sealing; the receipt does not invent unsupported internal attribution.",
            "Independent acceptance, activation and release remain separate signed gates.",
        ],
    }
    output = args.output or evidence / "delivery-contract.json"
    output.write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("PASS_HEPTA_KG_DELIVERY_EVIDENCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
