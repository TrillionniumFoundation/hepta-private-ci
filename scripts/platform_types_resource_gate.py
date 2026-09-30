#!/usr/bin/env python3
"""Validate actual benchmark samples; timing comparisons are not host acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess

CASES = (
    [f"hash-{mode}-{size}" for size in (8, 4096, 65536) for mode in ("buffered", "streaming")]
    + [f"registry-{operation}-{size}" for size in (8, 256) for operation in ("construct", "identity", "digest")]
    + [f"numeric-{operation}-{size}" for size in (8, 4096) for operation in ("convert", "verify")]
)
METHODOLOGY_PATHS = (
    "codex-rs/hepta-types/src/bin/platform-types-semantic-bench.rs",
    "codex-rs/hepta-types/src/bin/semantic_bench_support/allocator.rs",
    "scripts/platform_types_resource_gate.py",
    "scripts/run_platform_types_resource_qualification.sh",
)
SHA = re.compile(r"[0-9a-f]{40}\Z")

# Same-run normalized complexity ceilings are intentionally architecture-neutral.
# They catch accidental algorithmic regressions without pretending that a shared
# runner is a target-host latency authority.
COMPLEXITY_THRESHOLDS = {
    "hash-buffered-per-byte": 4.0,
    "hash-streaming-per-byte": 4.0,
    "registry-construct-per-entry": 4.0,
    "registry-identity": 4.0,
    "registry-digest": 4.0,
    "numeric-convert-per-element": 4.0,
    "numeric-verify-per-element": 4.0,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, f"invalid {name}")
    return value


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summarize(raw):
    require(raw.get("schema") == "hepta.platform-types.semantic-benchmark.v1", "benchmark schema")
    require(type(raw.get("samplesPerCase")) is int and raw["samplesPerCase"] == 17, "sample count")
    require(type(raw.get("iterationsPerSample")) is int and raw["iterationsPerSample"] == 64, "iteration count")
    require(raw.get("allocationMetric") == "successful-global-allocation-and-reallocation-requested-bytes", "allocation semantics")
    require(raw.get("timingAuthority") == "diagnostic-only", "timing claim")
    rows = raw.get("rows")
    require(isinstance(rows, list) and len(rows) == len(CASES) * 17, "incomplete samples")
    groups = {name: {} for name in CASES}
    for row in rows:
        require(isinstance(row, dict), "sample object")
        name = row.get("case")
        require(isinstance(name, str) and name in groups, "unknown case")
        sample = integer(row.get("sample"), "sample")
        require(sample < 17 and sample not in groups[name], "duplicate/out-of-range sample")
        require(integer(row.get("iterations"), "iterations", 1) == 64, "sample workload drift")
        integer(row.get("elapsedNs"), "elapsedNs", 1)
        calls = integer(row.get("allocationCalls"), "allocationCalls")
        reallocations = integer(row.get("reallocations"), "reallocations")
        size = integer(row.get("requestedBytes"), "requestedBytes")
        require(reallocations <= calls and (calls == 0) == (size == 0), "incoherent allocation sample")
        groups[name][sample] = row
    summaries = {}
    for name, samples in groups.items():
        require(set(samples) == set(range(17)), f"missing samples: {name}")
        times = sorted(row["elapsedNs"] / 64 for row in samples.values())
        summaries[name] = {
            "medianNs": statistics.median(times),
            "p95Ns": times[math.ceil(len(times) * 0.95) - 1],
            "medianAllocationCalls": statistics.median(row["allocationCalls"] / 64 for row in samples.values()),
            "medianRequestedBytes": statistics.median(row["requestedBytes"] / 64 for row in samples.values()),
        }
    for size in (8, 4096, 65536):
        for sample in range(17):
            buffered = groups[f"hash-buffered-{size}"][sample]
            streaming = groups[f"hash-streaming-{size}"][sample]
            require(streaming["requestedBytes"] < buffered["requestedBytes"], "streaming bytes did not decrease")
            require(streaming["allocationCalls"] <= buffered["allocationCalls"], "streaming allocation calls regressed")
    for size in (8, 256):
        for operation in ("identity", "digest"):
            require(all(row["allocationCalls"] == 0 for row in groups[f"registry-{operation}-{size}"].values()), "immutable lookup allocated")
    return summaries


def _normalized_ratio(summary, larger_case, larger_size, smaller_case, smaller_size, statistic):
    larger = summary[larger_case][statistic] / larger_size
    smaller = summary[smaller_case][statistic] / smaller_size
    require(larger > 0 and smaller > 0, "non-positive complexity measurement")
    return larger / smaller


def evaluate_complexity(summary):
    comparisons = {
        "hash-buffered-per-byte": (
            "hash-buffered-65536", 65536, "hash-buffered-4096", 4096
        ),
        "hash-streaming-per-byte": (
            "hash-streaming-65536", 65536, "hash-streaming-4096", 4096
        ),
        "registry-construct-per-entry": (
            "registry-construct-256", 256, "registry-construct-8", 8
        ),
        "registry-identity": (
            "registry-identity-256", 1, "registry-identity-8", 1
        ),
        "registry-digest": (
            "registry-digest-256", 1, "registry-digest-8", 1
        ),
        "numeric-convert-per-element": (
            "numeric-convert-4096", 4096, "numeric-convert-8", 8
        ),
        "numeric-verify-per-element": (
            "numeric-verify-4096", 4096, "numeric-verify-8", 8
        ),
    }
    ratios = {}
    for name, (larger_case, larger_size, smaller_case, smaller_size) in comparisons.items():
        ratios[name] = {
            statistic: _normalized_ratio(
                summary,
                larger_case,
                larger_size,
                smaller_case,
                smaller_size,
                statistic,
            )
            for statistic in ("medianNs", "p95Ns")
        }
        ceiling = COMPLEXITY_THRESHOLDS[name]
        require(
            all(value <= ceiling for value in ratios[name].values()),
            f"complexity regression: {name}",
        )
    return ratios


def evaluate(raw, source, tree, context, harness_digest, baseline=None, maximum_ratio=None):
    require(isinstance(source, str) and SHA.fullmatch(source), "source SHA")
    require(isinstance(tree, str) and SHA.fullmatch(tree), "tree SHA")
    require(isinstance(context, dict) and bool(context), "environment context")
    require(isinstance(harness_digest, str) and re.fullmatch(r"[0-9a-f]{64}", harness_digest), "harness digest")
    summary = summarize(raw)
    complexity_ratios = evaluate_complexity(summary)
    report = {
        "schema": "hepta.platform-types.resource-gate.v1",
        "sourceHead": source, "sourceTree": tree,
        "environment": context, "environmentDigest": digest_json(context),
        "harnessDigest": harness_digest,
        "methodologyFiles": list(METHODOLOGY_PATHS),
        "raw": raw, "summary": summary,
        "allocationGate": "passed",
        "complexityGate": "passed",
        "complexityThresholds": COMPLEXITY_THRESHOLDS,
        "complexityRatios": complexity_ratios,
        "latencyGate": "not_requested",
        "targetHostQualified": False, "independentAcceptance": False,
        "productActivation": False,
    }
    if baseline is not None:
        require(type(maximum_ratio) in (float, int) and math.isfinite(maximum_ratio) and 1 <= maximum_ratio <= 2, "explicit finite latency ratio required (1..2)")
        require(baseline.get("schema") == report["schema"], "baseline schema")
        require(SHA.fullmatch(baseline.get("sourceHead", "")), "baseline source")
        require(SHA.fullmatch(baseline.get("sourceTree", "")), "baseline tree")
        require(baseline.get("environment") == context and baseline.get("environmentDigest") == report["environmentDigest"], "baseline environment mismatch")
        require(baseline.get("methodologyFiles") == report["methodologyFiles"], "baseline methodology file set mismatch")
        require(baseline.get("harnessDigest") == harness_digest, "baseline methodology mismatch")
        prior = summarize(baseline["raw"])
        ratios = {}
        for name in CASES:
            ratios[name] = {key: summary[name][key] / prior[name][key] for key in ("medianNs", "p95Ns")}
            require(all(value <= maximum_ratio for value in ratios[name].values()), f"latency regression: {name}")
        report.update(latencyGate="passed", maximumLatencyRatio=maximum_ratio,
                      baselineSource=baseline["sourceHead"], latencyRatios=ratios)
    else:
        require(maximum_ratio is None, "latency threshold without baseline")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tree-sha", required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--maximum-latency-ratio", type=float)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()
    require(git("rev-parse", "HEAD") == args.source_sha, "HEAD changed")
    require(git("rev-parse", "HEAD^{tree}") == args.tree_sha, "tree changed")
    require(not git("status", "--porcelain", "--untracked-files=no"), "tracked worktree dirty")
    harness_digest = digest_json({
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in METHODOLOGY_PATHS
    })
    cpu = Path("/proc/cpuinfo")
    cpu_models = sorted(set(line for line in cpu.read_text().splitlines() if line.startswith(("model name", "vendor_id")))) if cpu.exists() else []
    context = {
        "system": platform.system(), "release": platform.release(),
        "machine": platform.machine(), "host": platform.node(), "cpuModels": cpu_models,
        "compiler": subprocess.check_output(["rustc", "--version", "--verbose"], text=True),
        "runnerImage": os.environ.get("ImageVersion", "unknown"),
        "buildProfile": "release", "allocator": "System/TrafficAllocator/v1",
        "rustflags": os.environ.get("RUSTFLAGS", ""),
        "encodedRustflags": os.environ.get("CARGO_ENCODED_RUSTFLAGS", ""),
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else [],
    }
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    report = evaluate(json.loads(args.raw.read_text()), args.source_sha, args.tree_sha,
                      context, harness_digest, baseline, args.maximum_latency_ratio)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        key: report[key]
        for key in (
            "sourceHead",
            "allocationGate",
            "complexityGate",
            "latencyGate",
            "targetHostQualified",
        )
    }))


if __name__ == "__main__":
    main()
