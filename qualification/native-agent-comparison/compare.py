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
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MODES = ("A", "B", "C")
SCALES = (64, 256, 1024, 4096)
REPOS = ("hepta", "runtime", "codex")
METRICS = ("wall_ms", "cpu_ms", "peak_rss_bytes", "peak_gpu_memory_bytes", "active_concurrency", "input_tokens", "output_tokens", "tool_calls")


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
    builds = base.get("mode_build_digests")
    require(isinstance(builds, dict) and set(builds) == set(MODES)
            and all(digest(value) for value in builds.values())
            and len(set(builds.values())) == len(MODES),
            "A/B/C executable and configuration manifests not pinned")
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
    require(isinstance(limits, dict) and set(limits) == {"max_input_tokens", "max_output_tokens", "timeout_ms", "max_cpu_ms", "max_rss_bytes", "max_gpu_memory_bytes", "max_active_concurrency", "max_tool_calls"}, "resource envelope missing")
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
    observation_digests = set()
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
        require(o.get("source_trees") == {r: base["sources"][r]["tree"] for r in REPOS}, "source tree drift")
        require(o.get("mode_build_digest") == base["mode_build_digests"][o["mode"]],
                "A/B/C built artifact or configuration drift")
        observation_digest = o.get("observation_digest")
        require(digest(observation_digest), "observation receipt digest invalid")
        require(observation_digest not in observation_digests, "duplicate observation receipt digest")
        observation_digests.add(observation_digest)
        require(o.get("idempotency_replayed") is False and type(o.get("unknown_effects_open")) is int and o["unknown_effects_open"] == 0, "unsafe replay or unresolved effect")
        require(type(o.get("task_success")) is bool and type(o.get("tool_correct")) is bool, "missing outcome truth")
        require(not o["task_success"] or o["tool_correct"], "task success conflicts with tool correctness")
        require(type(o.get("recovery_pass")) is bool, "missing recovery disposition")
        for name in METRICS:
            v = o.get(name)
            require(type(v) in (int, float) and v >= 0 and (type(v) is int or math.isfinite(v)), f"metric {name} invalid")
            if name in ("input_tokens", "output_tokens", "tool_calls",
                        "peak_rss_bytes", "peak_gpu_memory_bytes", "active_concurrency"):
                require(type(v) is int, f"metric {name} must be integer")
        require(o["peak_rss_bytes"] <= base["resource_limits"]["max_rss_bytes"], "RSS overrun")
        require(o["cpu_ms"] <= base["resource_limits"]["max_cpu_ms"], "CPU budget overrun")
        require(o["peak_gpu_memory_bytes"] <= base["resource_limits"]["max_gpu_memory_bytes"], "GPU memory overrun")
        require(1 <= o["active_concurrency"] <= min(o["scale"], base["resource_limits"]["max_active_concurrency"]),
                "active Cell concurrency invalid or over budget")
        require(o["tool_calls"] <= base["resource_limits"]["max_tool_calls"], "tool budget overrun")
        require(o["wall_ms"] <= base["resource_limits"]["timeout_ms"], "timeout exceeded")
        require(o["input_tokens"] <= base["resource_limits"]["max_input_tokens"], "input token budget exceeded")
        require(o["output_tokens"] <= base["resource_limits"]["max_output_tokens"], "output token budget exceeded")
    require(set(actual) == expected, f"incomplete paired A/B/C matrix: {len(actual)}/{len(expected)}")
    def summarize(subset: list[dict]) -> dict:
        require(bool(subset), "empty mode/scale summary")
        return {
            "cases": len(subset),
            "success_rate": sum(o["task_success"] for o in subset) / len(subset),
            "tool_correct_rate": sum(o["tool_correct"] for o in subset) / len(subset),
            "recovery_rate": sum(o["recovery_pass"] for o in subset) / len(subset),
            "wall_p95_ms": percentile([o["wall_ms"] for o in subset], .95),
            "wall_p99_ms": percentile([o["wall_ms"] for o in subset], .99),
            "peak_rss_bytes": max(o["peak_rss_bytes"] for o in subset),
            "peak_gpu_memory_bytes": max(o["peak_gpu_memory_bytes"] for o in subset),
            "max_active_concurrency": max(o["active_concurrency"] for o in subset),
            "cpu_ms_total": sum(o["cpu_ms"] for o in subset),
            "input_tokens_total": sum(o["input_tokens"] for o in subset),
            "output_tokens_total": sum(o["output_tokens"] for o in subset),
            "tool_calls_total": sum(o["tool_calls"] for o in subset),
        }

    summary = {mode: summarize([o for k, o in actual.items() if k[3] == mode])
               for mode in MODES}
    scale_summary = {
        str(scale): {
            mode: summarize([o for k, o in actual.items() if k[2] == scale and k[3] == mode])
            for mode in MODES
        }
        for scale in SCALES
    }
    # Show per-scale measured deltas; do not silently let a good 64-Cell
    # result mask a failure at 4096 Cells or grant any acceptance authority.
    deltas = {}
    for scale in SCALES:
        arms = scale_summary[str(scale)]
        base_mode = arms["A"]
        deltas[str(scale)] = {
            f"{mode}_vs_A": {
                "success_rate_delta": arms[mode]["success_rate"] - base_mode["success_rate"],
                "recovery_rate_delta": arms[mode]["recovery_rate"] - base_mode["recovery_rate"],
                "wall_p99_delta_ms": arms[mode]["wall_p99_ms"] - base_mode["wall_p99_ms"],
                "cpu_total_delta_ms": arms[mode]["cpu_ms_total"] - base_mode["cpu_ms_total"],
                "peak_rss_delta_bytes": arms[mode]["peak_rss_bytes"] - base_mode["peak_rss_bytes"],
                "peak_gpu_memory_delta_bytes": arms[mode]["peak_gpu_memory_bytes"] - base_mode["peak_gpu_memory_bytes"],
            }
            for mode in ("B", "C")
        }
    return {
        "status": "STRUCTURAL_COMPARABILITY_ONLY_NOT_INDEPENDENT_EVIDENCE",
        "independent_acceptance": False,
        "physical_execution_proven": False,
        "concurrent_throughput_proven": False,
        "task_count": len(base["tasks"]),
        "paired_case_count": len(expected) // 3,
        "mode_summaries": summary,
        "scale_summaries": scale_summary,
        "scale_deltas": deltas,
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
