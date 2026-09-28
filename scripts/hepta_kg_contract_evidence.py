#!/usr/bin/env python3
"""Bind knowledge.graph delivery contracts to exact execution evidence.

This validates execution artifacts only. It never promotes production,
independent acceptance, activation or release state.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
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
)
RECOVERY_TESTS = (
    "source_acknowledgement_retry_survives_wal_reader_and_reopen",
    "competing_memory_corrections_rollback_the_losing_source",
    "projection_failure_rolls_back_source_memory_and_facts_before_reopen",
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
        if len(fields) < 2 or not fields[0] or not fields[1].isdigit():
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


def require_test_names(log: Path, names: tuple[str, ...]) -> None:
    text = log.read_text(encoding="utf-8", errors="replace")
    missing = [name for name in names if name not in text]
    if missing:
        fail(f"{log.name} does not prove tests: {', '.join(missing)}")


def require_exact_single_test(log: Path) -> None:
    text = log.read_text(encoding="utf-8", errors="replace")
    summaries = SUMMARY.findall(text)
    if summaries != [("1", "0")]:
        fail(f"{log.name} must contain exactly one non-skipped successful test")


def parse_operation_metrics(log: Path) -> dict[str, Any]:
    rows = [
        line.split(OPERATION_PREFIX, 1)[1]
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
        if OPERATION_PREFIX in line
    ]
    if len(rows) != 1:
        fail(f"expected one operation metric receipt, got {len(rows)}")
    try:
        metrics = strict_object(rows[0])
    except (ValueError, json.JSONDecodeError) as error:
        fail(f"invalid operation metric receipt: {error}")
    if metrics.get("schema") != "hepta.knowledge-graph-operation-metrics.v1":
        fail("unexpected operation metric schema")
    for field in (
        "inputCloneNs",
        "buildValidateSealNs",
        "verifiedViewBuildNs",
        "hotQueryTotalNs",
        "publicationReceiptNs",
        "iterations",
    ):
        value = metrics.get(field)
        if type(value) is not int or value <= 0:
            fail(f"invalid operation metric {field}")
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


def contract(
    name: str,
    symbol: str,
    tests: list[str],
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "contract": name,
        "implementationSymbol": symbol,
        "tests": tests,
        "evidence": evidence,
        "state": "executed",
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
    results = read_results(evidence / "results.tsv")
    required = COMMON_CHECKS + (
        KERNEL_CHECKS if args.profile == "kernel" else PRODUCT_CHECKS
    )
    if args.profile == "product" and args.lane == "source-head":
        required += ("release-measurement", "hosted-budget")
    require_checks(results, required)

    operation_metrics = parse_operation_metrics(evidence / "operation-metrics.log")
    contracts: list[dict[str, Any]] = []
    if args.profile == "kernel":
        require_test_names(evidence / "kg-kernel.log", QUERY_TESTS)
        contracts.append(
            contract(
                "bounded external query with exact failure semantics",
                "VerifiedKnowledgeGenerationV2::query_relations_with_work_budget",
                list(QUERY_TESTS),
                ["kg-kernel.log", "operation-metrics.log"],
            )
        )
    else:
        require_test_names(evidence / "cognitive-owner.log", RECOVERY_TESTS)
        require_exact_single_test(evidence / "crash-reopen.log")
        require_exact_single_test(evidence / "history-reopen.log")
        contracts.extend(
            [
                contract(
                    "lost acknowledgement retry is idempotent across WAL and reopen",
                    "CognitiveStore::append_source",
                    [RECOVERY_TESTS[0]],
                    ["cognitive-owner.log"],
                ),
                contract(
                    "competing publication commits one head and rolls back the loser",
                    "CognitiveStore::correct_with_kg",
                    [RECOVERY_TESTS[1]],
                    ["cognitive-owner.log"],
                ),
                contract(
                    "failed projection publication leaves the exact predecessor",
                    "CognitiveStore::remember_with_kg",
                    [RECOVERY_TESTS[2]],
                    ["cognitive-owner.log"],
                ),
                contract(
                    "SIGKILL at both semantic-receipt/current-pointer windows restores predecessor",
                    "qualification_kg_projection_crash_windows_restore_exact_predecessor",
                    [
                        "before_semantic_receipt",
                        "after_semantic_receipt_before_current_pointer",
                    ],
                    ["crash-reopen.log"],
                ),
                contract(
                    "history deletion cannot resurrect across reopen",
                    "qualification_kg_history_reopen_no_resurrection",
                    ["qualification_kg_history_reopen_no_resurrection"],
                    ["history-reopen.log"],
                ),
            ]
        )

    release: dict[str, Any] | None = None
    if args.profile == "product" and args.lane == "source-head":
        release = parse_release_measurement(evidence / "release-measurement.json")
        if release["sourceCommit"] != args.tested_sha:
            fail("release measurement source identity mismatch")

    document = {
        "schema": "hepta.knowledge-graph-delivery-evidence.v1",
        "sourceCommit": args.source_sha,
        "baseCommit": args.base_sha,
        "testedCommit": args.tested_sha,
        "testedTree": args.tested_tree,
        "profile": args.profile,
        "lane": args.lane,
        "environment": {
            "runnerOs": platform.system(),
            "runnerMachine": platform.machine(),
            "python": platform.python_version(),
        },
        "contracts": contracts,
        "operationMetrics": operation_metrics,
        "releaseMeasurement": release,
        "claimBoundary": {
            "sourceChecksPassed": True,
            "nativeBinaryCompiled": True,
            "scenarioExecuted": True,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "openReasons": [
            "Hosted runner measurements are regression evidence, not operator target-host qualification.",
            "The public builder combines build, validation and sealing; the receipt does not invent unsupported internal attribution.",
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
