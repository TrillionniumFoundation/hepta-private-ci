#!/usr/bin/env python3
"""P5 structural, fail-closed paired Cell-split evaluation (no deployment authority).

Input is a frozen cohort manifest and independently obtained observations. Source
and outcome claims inside JSON are *not* authenticated by this offline checker.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from pathlib import Path

ARMS = ("no_change", "reuse", "fixed_count", "shared_head", "sparse_moe", "split")
SCALES = (64, 256, 1024, 4096)
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
REQUIRED_METRICS = ("wall_ms", "cpu_ms", "peak_rss_bytes", "input_tokens", "output_tokens", "tool_calls")


class GateError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(DIGEST.fullmatch(value)) and value != "0" * 64


def require_digest(value: object, what: str) -> None:
    require(valid_digest(value), f"invalid {what} digest")


def validate_plan(plan: object) -> tuple[dict, list[dict]]:
    require(isinstance(plan, dict) and plan.get("schema") == "hepta.cell-split-comparison.v1", "plan schema")
    require(plan.get("arms") == list(ARMS) and plan.get("scales") == list(SCALES), "arm/scale drift")
    for field in ("source_digest", "model_profile_digest", "target_profile_digest", "objective_digest", "evaluation_code_digest"):
        require_digest(plan.get(field), field)
    limits = plan.get("limits")
    require(isinstance(limits, dict) and set(limits) == set(REQUIRED_METRICS), "limits schema")
    for key, value in limits.items():
        require(type(value) is int and 0 < value < 10**13, f"invalid limit: {key}")
    require(type(plan.get("bootstrap_seed")) is int and plan["bootstrap_seed"] >= 0, "bootstrap seed")
    require(type(plan.get("min_future_group_gain")) in (float, int)
            and 0 <= plan["min_future_group_gain"] < 1, "future gain threshold")
    require(type(plan.get("max_old_task_regression")) in (float, int)
            and 0 <= plan["max_old_task_regression"] < 1, "old task regression threshold")
    tasks = plan.get("tasks")
    require(isinstance(tasks, list) and tasks, "frozen tasks missing")
    seen = set()
    split_groups = {"train": set(), "calibration": set(), "test": set(), "future": set()}
    split_families = {key: set() for key in split_groups}
    # Preserve original-file identity across repeated seeds, but refuse reuse
    # between independent cohort groups or across train/test/future boundaries.
    fixture_owners = {}
    # The future bootstrap is grouped by source family. Treating five aliases
    # of one family as five independent future groups inflates confidence.
    future_group_families = {}
    future_family_groups = {}
    evaluation = []
    for task in tasks:
        require(isinstance(task, dict) and set(task) == {"id", "family", "group", "split", "seed", "fixture_digest", "oracle_digest"}, "task schema")
        for name in ("id", "family", "group"):
            require(isinstance(task[name], str) and 1 <= len(task[name]) <= 128, f"task {name}")
        require(task["id"] not in seen, "duplicate task")
        seen.add(task["id"])
        require(type(task["seed"]) is int and task["seed"] >= 0, "task seed")
        require_digest(task["fixture_digest"], "fixture")
        require_digest(task["oracle_digest"], "oracle")
        subset = task["split"]
        require(subset in split_groups, "invalid task split")
        require(task["group"] not in set().union(*(v for k, v in split_groups.items() if k != subset)), "group crosses data split")
        owner = (subset, task["group"])
        prior_owner = fixture_owners.setdefault(task["fixture_digest"], owner)
        require(prior_owner == owner, "fixture reused across independent groups")
        if subset == "future":
            prior_family = future_group_families.setdefault(task["group"], task["family"])
            require(prior_family == task["family"], "future group mixes families")
            prior_group = future_family_groups.setdefault(task["family"], task["group"])
            require(prior_group == task["group"], "future family crosses independent groups")
        split_groups[subset].add(task["group"])
        split_families[subset].add(task["family"])
        if subset in ("test", "future"):
            evaluation.append(task)
    require(len(split_groups["future"]) >= 5 and len(split_groups["test"]) >= 1, "insufficient grouped future or old-task holdout")
    require(split_families["future"].isdisjoint(split_families["train"] | split_families["calibration"] | split_families["test"]), "future family leaked into development/old tasks")
    require(split_families["test"].isdisjoint(split_families["train"] | split_families["calibration"]), "test family leaked into development")
    return plan, evaluation


def percentile(values: list[float], fraction: float) -> float:
    data = sorted(values)
    return data[max(0, math.ceil(fraction * len(data)) - 1)]


def compare(plan: object, observations: object) -> dict:
    plan, tasks = validate_plan(plan)
    require(isinstance(observations, list), "observation array required")
    task_by_id = {t["id"]: t for t in tasks}
    expected = {(t["id"], t["seed"], scale, arm) for t in tasks for scale in SCALES for arm in ARMS}
    actual = {}
    for item in observations:
        require(isinstance(item, dict) and item.get("schema") == "hepta.cell-split-observation.v1", "observation schema")
        key = (item.get("task_id"), item.get("seed"), item.get("scale"), item.get("arm"))
        require(key in expected and key not in actual, "missing task definition or duplicate observation")
        task = task_by_id[key[0]]
        require(item.get("fixture_digest") == task["fixture_digest"] and item.get("oracle_digest") == task["oracle_digest"], "fixture/oracle drift")
        for f in ("source_digest", "model_profile_digest", "target_profile_digest", "objective_digest", "evaluation_code_digest"):
            require(item.get(f) == plan[f], f"{f} drift")
        require(item.get("limits") == plan["limits"], "unequal resource limits")
        require(item.get("idempotency_replayed") is False and type(item.get("unknown_effects")) is int and item["unknown_effects"] == 0, "unsafe effect or unknown outcome")
        require(type(item.get("success")) is bool and type(item.get("tool_correct")) is bool, "unverified outcome format")
        require_digest(item.get("observation_digest"), "observation")
        for metric in REQUIRED_METRICS:
            value = item.get(metric)
            require(type(value) is int and 0 <= value <= plan["limits"][metric], f"invalid or over-budget {metric}")
        actual[key] = item
    require(set(actual) == expected, f"incomplete paired matrix: {len(actual)}/{len(expected)}")
    results = {}
    for scale in SCALES:
        future_groups = sorted({t["group"] for t in tasks if t["split"] == "future"})
        diffs = []
        for group in future_groups:
            rows = [t for t in tasks if t["split"] == "future" and t["group"] == group]
            def mean_success(arm: str) -> float:
                return sum(actual[(t["id"], t["seed"], scale, arm)]["success"] for t in rows) / len(rows)
            diffs.append(mean_success("split") - max(mean_success(arm) for arm in ARMS if arm != "split"))
        rng = random.Random(plan["bootstrap_seed"] + scale)
        bootstrap = [sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(1024)]
        lower = percentile(bootstrap, .05)
        old_rows = [t for t in tasks if t["split"] == "test"]
        old_diffs = [int(actual[(t["id"], t["seed"], scale, "split")]["success"])
                     - int(actual[(t["id"], t["seed"], scale, "no_change")]["success"])
                     for t in old_rows]
        old_regression = sum(old_diffs) / len(old_diffs)
        by_arm = {}
        for arm in ARMS:
            rows = [actual[(t["id"], t["seed"], scale, arm)] for t in tasks]
            by_arm[arm] = {
                "success_rate": sum(x["success"] for x in rows) / len(rows),
                "tool_correct_rate": sum(x["tool_correct"] for x in rows) / len(rows),
                "p95_wall_ms": percentile([x["wall_ms"] for x in rows], .95),
                "p99_wall_ms": percentile([x["wall_ms"] for x in rows], .99),
                "peak_rss_bytes": max(x["peak_rss_bytes"] for x in rows),
                "total_cpu_ms": sum(x["cpu_ms"] for x in rows),
                "total_tokens": sum(x["input_tokens"] + x["output_tokens"] for x in rows),
            }
        results[str(scale)] = {
            "future_group_count": len(diffs),
            "future_gain_bootstrap_lower_95_one_sided": lower,
            "old_task_delta_vs_no_change": old_regression,
            "candidate_meets_structural_metrics": lower > plan["min_future_group_gain"]
                and old_regression >= -plan["max_old_task_regression"],
            "arms": by_arm,
        }
    return {
        "status": "HOLD_NO_GO_INDEPENDENT_EVIDENCE_REQUIRED",
        "independent_acceptance": False,
        "physical_execution_proven": False,
        "all_scales_meet_structural_metrics": all(v["candidate_meets_structural_metrics"] for v in results.values()),
        "scales": results,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: cell_split.py PLAN.json OBSERVATIONS.json", file=sys.stderr)
        return 2
    try:
        result = compare(json.loads(Path(argv[0]).read_text()), json.loads(Path(argv[1]).read_text()))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (GateError, OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"HOLD_NO_GO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
