#!/usr/bin/env python3
"""Evaluate real kernel.authority hot-path diagnostics against site-owned limits.

A pass means one validated collection stayed within the supplied measurement
policy. It never authorizes a runtime storage migration, production SLO,
activation, or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import capacity_matrix as capacity

POLICY_SCHEMA = "hepta.kernel-authority-hot-path-policy.v1"
DECISION_SCHEMA = "hepta.kernel-authority-hot-path-decision.v1"
SCHEMA_VERSION = 1
POINTS = capacity.POINTS
METRICS = capacity.METRICS
LIMIT_FIELDS = {
    "metric",
    "maxP99UsByPoint",
    "maxBytesTouchedByPoint",
    "maxTimePerHistoryGrowthPermille",
    "maxBytesPerHistoryGrowthPermille",
}
NON_AUTHORITY_FIELDS = (
    "runtimeOptimizationAuthorized",
    "productionSloGranted",
    "independentAcceptance",
    "activationGranted",
    "releaseGranted",
)


class Invalid(ValueError):
    """The policy, collection, or decision input is invalid."""


def need(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def exact(value: dict[str, Any], fields: set[str], label: str) -> None:
    need(set(value) == fields, f"{label}: exact fields required")


def integer(value: Any, label: str, minimum: int = 0) -> int:
    need(type(value) is int and value >= minimum, f"{label}: invalid integer")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def read_object(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Invalid(f"{label}: read failed: {error}") from error

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in rows:
            need(key not in output, f"{label}: duplicate field {key}")
            output[key] = value
        return output

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Invalid(f"{label}: invalid JSON: {error}") from error
    need(isinstance(value, dict), f"{label}: object required")
    return value, hashlib.sha256(raw).hexdigest()


def write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def point_limits(value: Any, label: str) -> dict[str, int]:
    need(isinstance(value, dict), f"{label}: object required")
    exact(value, set(POINTS), label)
    return {
        point: integer(value[point], f"{label}.{point}", 1)
        for point in POINTS
    }


def validate_policy(
    value: dict[str, Any],
    selected_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    exact(
        value,
        {
            "schema",
            "schemaVersion",
            "candidate",
            "profileId",
            "limits",
            "runtimeOptimizationAuthorized",
            "productionSloGranted",
            "independentAcceptance",
            "activationGranted",
            "releaseGranted",
        },
        "policy",
    )
    need(
        value["schema"] == POLICY_SCHEMA
        and value["schemaVersion"] == SCHEMA_VERSION,
        "policy: unsupported schema",
    )
    need(
        capacity.candidate(value["candidate"], "policy.candidate")
        == selected_plan["candidate"],
        "policy: candidate mismatch",
    )
    need(
        capacity.identifier(value["profileId"], "policy.profileId")
        == selected_plan["profileId"],
        "policy: profile mismatch",
    )
    for field in NON_AUTHORITY_FIELDS:
        need(value[field] is False, f"policy: {field} must remain false")
    need(isinstance(value["limits"], list), "policy.limits: array required")
    limits: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value["limits"]):
        label = f"policy.limits[{index}]"
        need(isinstance(raw, dict), f"{label}: object required")
        exact(raw, LIMIT_FIELDS, label)
        metric = raw["metric"]
        need(
            isinstance(metric, str)
            and metric in METRICS
            and metric not in limits,
            f"{label}.metric: invalid or duplicate",
        )
        limits[metric] = {
            "metric": metric,
            "maxP99UsByPoint": point_limits(
                raw["maxP99UsByPoint"],
                f"{label}.maxP99UsByPoint",
            ),
            "maxBytesTouchedByPoint": point_limits(
                raw["maxBytesTouchedByPoint"],
                f"{label}.maxBytesTouchedByPoint",
            ),
            "maxTimePerHistoryGrowthPermille": integer(
                raw["maxTimePerHistoryGrowthPermille"],
                f"{label}.maxTimePerHistoryGrowthPermille",
                1,
            ),
            "maxBytesPerHistoryGrowthPermille": integer(
                raw["maxBytesPerHistoryGrowthPermille"],
                f"{label}.maxBytesPerHistoryGrowthPermille",
                1,
            ),
        }
    need(set(limits) == set(METRICS), "policy: complete metric limits required")
    return value, limits


def ceil_div(numerator: int, denominator: int) -> int:
    need(denominator > 0, "growth denominator must be positive")
    return (numerator + denominator - 1) // denominator


def relative_per_history_permille(
    previous_work: int,
    current_work: int,
    previous_history: int,
    current_history: int,
) -> int:
    need(previous_history > 0, "previous history must be positive")
    need(current_history > previous_history, "history must increase")
    return ceil_div(
        current_work * previous_history * 1_000,
        max(previous_work, 1) * current_history,
    )


def diagnostic_index(rows: Any) -> dict[tuple[str, str], dict[str, Any]]:
    need(isinstance(rows, list), "diagnostics: array required")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        need(isinstance(raw, dict), "diagnostic row: object required")
        metric = raw.get("metric")
        point = raw.get("point")
        identity = (metric, point)
        need(
            metric in METRICS and point in POINTS and identity not in indexed,
            "diagnostics: invalid or duplicate identity",
        )
        for field in ("p99Us", "bytesTouched", "historyUnits"):
            integer(raw.get(field), f"diagnostic {metric}/{point}.{field}")
        indexed[identity] = raw
    need(
        set(indexed)
        == {(metric, point) for metric in METRICS for point in POINTS},
        "diagnostics: complete 5x5 set required",
    )
    return indexed


def evaluate_diagnostics(
    rows: Any,
    limits: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    indexed = diagnostic_index(rows)
    results: list[dict[str, Any]] = []
    investigations: list[str] = []
    recommendations = {
        "final_use_frontier_hash": (
            "evaluate an incremental authenticated frontier/checkpoint design "
            "without changing external-frontier-first commit or exact recovery"
        ),
        "lease_state_clone": (
            "evaluate copy-on-write owner transactions while preserving one owner "
            "and exact predecessor/revision conflict semantics"
        ),
        "lease_image_serialize": (
            "evaluate an incremental durable lease image with full replay and "
            "anti-rollback proof before replacing atomic complete images"
        ),
        "clock_floor_persist": (
            "evaluate bounded clock-floor write coalescing only with additional "
            "conservative uncertainty and restart counterexamples"
        ),
        "restart_rebuild": (
            "evaluate checkpointed restart only when every committed prefix, "
            "frontier, pending revocation, and replay identity remains provable"
        ),
    }
    for metric in METRICS:
        policy = limits[metric]
        point_checks: list[dict[str, Any]] = []
        ordered = [indexed[(metric, point)] for point in POINTS]
        for point, row in zip(POINTS, ordered, strict=True):
            p99 = row["p99Us"]
            touched = row["bytesTouched"]
            p99_limit = policy["maxP99UsByPoint"][point]
            bytes_limit = policy["maxBytesTouchedByPoint"][point]
            point_checks.append(
                {
                    "point": point,
                    "p99Us": p99,
                    "maxP99Us": p99_limit,
                    "p99Pass": p99 <= p99_limit,
                    "bytesTouched": touched,
                    "maxBytesTouched": bytes_limit,
                    "bytesPass": touched <= bytes_limit,
                }
            )
        growth_checks: list[dict[str, Any]] = []
        positive = [row for row in ordered if row["historyUnits"] > 0]
        need(len(positive) >= 2, f"{metric}: insufficient positive history points")
        for previous, current in zip(positive, positive[1:], strict=False):
            time_relative = relative_per_history_permille(
                previous["p99Us"],
                current["p99Us"],
                previous["historyUnits"],
                current["historyUnits"],
            )
            bytes_relative = relative_per_history_permille(
                previous["bytesTouched"],
                current["bytesTouched"],
                previous["historyUnits"],
                current["historyUnits"],
            )
            growth_checks.append(
                {
                    "fromPoint": previous["point"],
                    "toPoint": current["point"],
                    "timePerHistoryGrowthPermille": time_relative,
                    "maxTimePerHistoryGrowthPermille": policy[
                        "maxTimePerHistoryGrowthPermille"
                    ],
                    "timeGrowthPass": time_relative
                    <= policy["maxTimePerHistoryGrowthPermille"],
                    "bytesPerHistoryGrowthPermille": bytes_relative,
                    "maxBytesPerHistoryGrowthPermille": policy[
                        "maxBytesPerHistoryGrowthPermille"
                    ],
                    "bytesGrowthPass": bytes_relative
                    <= policy["maxBytesPerHistoryGrowthPermille"],
                }
            )
        passed = all(
            row["p99Pass"] and row["bytesPass"] for row in point_checks
        ) and all(
            row["timeGrowthPass"] and row["bytesGrowthPass"]
            for row in growth_checks
        )
        if not passed:
            investigations.append(recommendations[metric])
        results.append(
            {
                "metric": metric,
                "pointChecks": point_checks,
                "growthChecks": growth_checks,
                "passed": passed,
            }
        )
    return results, investigations


def decision(
    selected_plan: dict[str, Any],
    collection: dict[str, Any],
    policy_sha256: str,
    collection_sha256: str,
    results: list[dict[str, Any]],
    investigations: list[str],
) -> dict[str, Any]:
    passed = all(result["passed"] for result in results)
    return {
        "schema": DECISION_SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "candidate": selected_plan["candidate"],
        "profileId": selected_plan["profileId"],
        "host": collection["host"],
        "policySha256": policy_sha256,
        "collectionSha256": collection_sha256,
        "metricResults": results,
        "recommendedInvestigations": investigations,
        "passed": passed,
        "runtimeOptimizationAuthorized": False,
        "productionSloGranted": False,
        "independentAcceptance": False,
        "activationGranted": False,
        "releaseGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan_value, _plan_sha = read_object(args.plan, "plan")
        selected_plan = capacity.validate_plan(plan_value)
        collection_value, collection_sha = read_object(
            args.collection,
            "collection",
        )
        collection = capacity.validate_collection(selected_plan, collection_value)
        policy_value, policy_sha = read_object(args.policy, "policy")
        _validated_policy, limits = validate_policy(policy_value, selected_plan)
        results, investigations = evaluate_diagnostics(
            collection["hotPathDiagnostics"],
            limits,
        )
        result = decision(
            selected_plan,
            collection,
            policy_sha,
            collection_sha,
            results,
            investigations,
        )
        write_atomic(args.output, result)
        return 0 if result["passed"] else 1
    except (Invalid, capacity.Invalid, OSError, ValueError) as error:
        print(f"kernel.authority hot-path gate failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
