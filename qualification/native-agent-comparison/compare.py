#!/usr/bin/env python3
"""Fail-closed, source-pinned A/B/C receipt comparability checker.

This does not run Codex, a native agent, or a physical host. The resulting
statistics are untrusted until independently attested by the evidence owner.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MODES = ("A", "B", "C")
SCALES = (64, 256, 1024, 4096)
REPOS = ("hepta", "runtime", "codex")
METRICS = ("wall_ms", "peak_rss_bytes", "input_tokens", "output_tokens", "tool_calls")


class ComparisonError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ComparisonError(message)


def digest(value: object) -> bool:
    return isinstance(value, str) and bool(DIGEST.fullmatch(value)) and value != "0" * 64


def head(value: object) -> bool:
    return isinstance(value, str) and bool(SHA.fullmatch(value)) and value != "0" * 40


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def checked_baseline(base: object) -> dict:
    require(isinstance(base, dict) and base.get("schema") == "hepta.native-abc.v1", "baseline schema")
    require(set(base.get("sources", {})) == set(REPOS), "three source owners required")
    for owner in REPOS:
        source = base["sources"][owner]
        require(isinstance(source, dict) and head(source.get("commit")) and head(source.get("tree")), f"source {owner} exact commit/tree")
    require(base.get("modes") == list(MODES) and base.get("scales") == list(SCALES), "mode/scale matrix changed")
    tasks = base.get("tasks")
    require(isinstance(tasks, list) and len(tasks) > 0, "no frozen task fixtures: HOLD_NO_GO")
    seen = set()
    for task in tasks:
        require(isinstance(task, dict), "invalid task")
        name = task.get("task_id")
        require(isinstance(name, str) and 1 <= len(name) <= 128 and name not in seen, "duplicate/invalid task id")
        seen.add(name)
        require(digest(task.get("fixture_digest")) and digest(task.get("answer_oracle_digest")), "task/oracle not pinned")
        require(isinstance(task.get("seed"), int) and not isinstance(task.get("seed"), bool) and task["seed"] >= 0, "seed not pinned")
    limits = base.get("resource_limits")
    require(isinstance(limits, dict) and set(limits) == {"max_input_tokens", "max_output_tokens", "timeout_ms", "max_rss_bytes", "max_tool_calls"}, "resource envelope missing")
    for name, value in limits.items():
        require(type(value) is int and 0 < value < 10**12, f"resource {name} invalid")
    require(digest(base.get("target_profile_digest")), "target host profile not pinned")
    require(digest(base.get("model_profile_digest")), "model profile not pinned")
    return base


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(len(ordered) * p) - 1)])


def compare(base: object, observations: object) -> dict:
    base = checked_baseline(base)
    require(isinstance(observations, list), "observations must be an array")
    expected = {(t["task_id"], t["seed"], scale, mode)
                for t in base["tasks"] for scale in SCALES for mode in MODES}
    task_index = {t["task_id"]: t for t in base["tasks"]}
    actual = {}
    metrics = defaultdict(lambda: defaultdict(list))
    for o in observations:
        require(isinstance(o, dict) and o.get("schema") == "hepta.native-abc-observation.v1", "observation schema")
        key = (o.get("task_id"), o.get("seed"), o.get("scale"), o.get("mode"))
        require(key in expected and key not in actual, "unknown or duplicate task/seed/scale/mode")
        actual[key] = o
        task = task_index[o["task_id"]]
        require(o.get("fixture_digest") == task["fixture_digest"], "fixture mutation")
        require(o.get("answer_oracle_digest") == task["answer_oracle_digest"], "oracle mutation")
        require(o.get("target_profile_digest") == base["target_profile_digest"], "target profile drift")
        require(o.get("model_profile_digest") == base["model_profile_digest"], "model profile drift")
        require(canonical(o.get("resource_limits")) == canonical(base["resource_limits"]), "resource envelope drift")
        require(o.get("source_commits") == {r: base["sources"][r]["commit"] for r in REPOS}, "source identity drift")
        require(o.get("idempotency_replayed") is False and type(o.get("unknown_effects_open")) is int and o["unknown_effects_open"] == 0, "unsafe replay or unresolved effect")
        require(type(o.get("task_success")) is bool and type(o.get("tool_correct")) is bool, "missing outcome truth")
        require(type(o.get("recovery_pass")) is bool, "missing recovery disposition")
        for name in METRICS:
            v = o.get(name)
            require(type(v) in (int, float) and math.isfinite(v) and v >= 0, f"metric {name} invalid")
            if name in ("input_tokens", "output_tokens", "tool_calls", "peak_rss_bytes"):
                require(type(v) is int, f"metric {name} must be integer")
            metrics[o["mode"]][name].append(v)
        require(o["peak_rss_bytes"] <= base["resource_limits"]["max_rss_bytes"], "RSS overrun")
        require(o["tool_calls"] <= base["resource_limits"]["max_tool_calls"], "tool budget overrun")
        require(o["wall_ms"] <= base["resource_limits"]["timeout_ms"], "timeout exceeded")
        require(o["input_tokens"] <= base["resource_limits"]["max_input_tokens"], "input token budget exceeded")
        require(o["output_tokens"] <= base["resource_limits"]["max_output_tokens"], "output token budget exceeded")
    require(set(actual) == expected, f"incomplete paired A/B/C matrix: {len(actual)}/{len(expected)}")
    summary = {}
    for mode in MODES:
        subset = [o for k, o in actual.items() if k[3] == mode]
        summary[mode] = {
            "cases": len(subset),
            "success_rate": sum(o["task_success"] for o in subset) / len(subset),
            "tool_correct_rate": sum(o["tool_correct"] for o in subset) / len(subset),
            "recovery_rate": sum(o["recovery_pass"] for o in subset) / len(subset),
            "wall_p95_ms": percentile(metrics[mode]["wall_ms"], .95),
            "wall_p99_ms": percentile(metrics[mode]["wall_ms"], .99),
            "peak_rss_bytes": max(metrics[mode]["peak_rss_bytes"]),
            "input_tokens_total": sum(metrics[mode]["input_tokens"]),
            "output_tokens_total": sum(metrics[mode]["output_tokens"]),
            "tool_calls_total": sum(metrics[mode]["tool_calls"]),
        }
    return {
        "status": "STRUCTURAL_COMPARABILITY_ONLY_NOT_INDEPENDENT_EVIDENCE",
        "independent_acceptance": False,
        "physical_execution_proven": False,
        "task_count": len(base["tasks"]),
        "paired_case_count": len(expected) // 3,
        "mode_summaries": summary,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: compare.py BASELINE.json OBSERVATIONS.json", file=sys.stderr)
        return 2
    try:
        baseline = json.loads(Path(argv[0]).read_text())
        observations = json.loads(Path(argv[1]).read_text())
        print(json.dumps(compare(baseline, observations), indent=2, sort_keys=True))
        return 0
    except (ComparisonError, OSError, json.JSONDecodeError, TypeError, KeyError) as error:
        print(f"HOLD_NO_GO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
