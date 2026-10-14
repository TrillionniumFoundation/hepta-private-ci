#!/usr/bin/env python3
"""Compare isolated Q24 fixture costs against V1 without granting authority.

This script checks every one of five arm / four cell-count samples, protects
against duplicate/mixed/forged claims, and reports ratios observed on one
untrusted CI host. Relative fixture costs cannot establish learning benefit,
production p99, causal speedup, training fairness or NDU utility.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from typing import Any

from run_shadow_probe_matrix import ARMS, SCALES, EVIDENCE_KIND, validate_probe

SCHEMA = "hepta.neuron.mechanism-only-matrix.v1"
SUMMARY_SCHEMA = "hepta.neuron.five-arm-mechanism-cost-summary.v1"


def require(test: bool, explanation: str) -> None:
    if not test:
        raise ValueError(explanation)


def ratio(numerator: int | float, denominator: int | float) -> str:
    """Exact decimal comparison of measured numeric fields, not inference."""
    try:
        a, b = Decimal(str(numerator)), Decimal(str(denominator))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid measured numeric ratio") from exc
    require(a.is_finite() and b.is_finite() and a > 0 and b > 0,
            "non-positive or nonfinite measured numeric ratio")
    return str((a / b).quantize(Decimal("0.000001")))


def analyze(report: Any) -> dict[str, Any]:
    require(isinstance(report, dict) and set(report) == {
        "schema", "source_evidence_kind", "target_host_qualified",
        "trained_artifacts_qualified", "ndu_eligible", "trace_sha256",
        "arms", "scales", "results", "warning",
    }, "not an exact, complete mechanism fixture matrix")
    require(report["schema"] == SCHEMA and
            report["source_evidence_kind"] == EVIDENCE_KIND,
            "source is not the expected untrained fixture matrix")
    for field in ("target_host_qualified", "trained_artifacts_qualified", "ndu_eligible"):
        require(report[field] is False, f"{field}: forbidden authority assertion")
    require(report["arms"] == list(ARMS) and report["scales"] == list(SCALES),
            "different or incomplete registered comparison arms or scales")
    digest = report["trace_sha256"]
    require(isinstance(digest, str) and len(digest) == 64
            and digest != "0" * 64 and all(c in "0123456789abcdef" for c in digest),
            "invalid original input fixture digest")
    require(isinstance(report["results"], list) and
            len(report["results"]) == len(ARMS) * len(SCALES),
            "must have exactly 20 native arm/scale measurements")
    records: dict[tuple[str, int], dict[str, Any]] = {}
    events = None
    for measurement in report["results"]:
        require(isinstance(measurement, dict), "invalid native record")
        arm, scale = measurement.get("arm"), measurement.get("cells")
        require(arm in ARMS and type(scale) is int and scale in SCALES,
                "unexpected arm or Cell count")
        key = arm, scale
        require(key not in records, "duplicate native arm/scale measurement")
        count = measurement.get("logical_tick_count")
        require(type(count) is int and count > 0 and count % scale == 0,
                "invalid measured logical Tick count")
        n = count // scale
        require(1 <= n <= 1024, "invalid bounded event count")
        if events is None:
            events = n
        require(events == n, "different event counts between native arms")
        require(measurement.get("trace_sha256") == digest,
                "mixed original trace digests")
        validated = validate_probe(measurement, arm=arm, cells=scale,
                                   digest=digest, events=n)
        require(validated.get("all_model_parameter_budgets_matched") is False,
                "fixture reports matched full-model parameter budgets")
        for field in ("p50_tick_nanos", "p95_tick_nanos", "p99_tick_nanos",
                      "process_wall_micros", "process_peak_rss_bytes",
                      "mechanism_tick_throughput_per_second_milli"):
            require(type(validated.get(field)) is int and validated[field] > 0,
                    f"{field}: missing positive measured quantity")
        records[key] = validated
    require(len(records) == 20, "missing registered scale/arm pair")
    comparison = []
    for scale in SCALES:
        baseline = records["v1", scale]
        rows = []
        for arm in ARMS:
            trial = records[arm, scale]
            rows.append({
                "arm": arm,
                "cell_count": scale,
                "p99_tick_nanos": trial["p99_tick_nanos"],
                "p99_ratio_to_v1": ratio(trial["p99_tick_nanos"],
                                         baseline["p99_tick_nanos"]),
                "process_peak_rss_bytes": trial["process_peak_rss_bytes"],
                "peak_rss_ratio_to_v1": ratio(trial["process_peak_rss_bytes"],
                                              baseline["process_peak_rss_bytes"]),
                "mechanism_tick_throughput_per_second_milli": (
                    trial["mechanism_tick_throughput_per_second_milli"]
                ),
                "throughput_ratio_to_v1": ratio(
                    trial["mechanism_tick_throughput_per_second_milli"],
                    baseline["mechanism_tick_throughput_per_second_milli"],
                ),
                "original_frontier_digest": trial["frontier_digest"],
            })
        comparison.append({"cells": scale, "arms": rows})
    return {
        "schema": SUMMARY_SCHEMA,
        "experiment": "ISOLATED_SYNTHETIC_Q24_MECHANISM_ONLY",
        "original_trace_sha256": digest,
        "events_per_cell": events,
        "comparisons": comparison,
        "total_verified_native_records": 20,
        "verified_real_training": False,
        "verified_independent_evaluator": False,
        "verified_same_budget_full_model_execution": False,
        "qualified_target_host": False,
        "qualified_p99_sla": False,
        "verified_checkpoint_cas_wal_generation_fence": False,
        "ndu_eligible": False,
        "production_qualification": False,
        "decision": "NO_MODEL_PROMOTION",
        "limitations": [
            "V1 and candidates share a frozen synthetic 32-channel trace, not paired real tasks.",
            "Measurements are from distinct processes and serial ticks on one CI host, without a target-host identity or load profile.",
            "Workload includes repeated config validation, hashing, allocations and checkpoint reconstruction; it excludes full Encoder, training and worker/queue/CAS/WAL costs.",
            "The ratios are descriptive same-run comparisons; not scientifically controlled confidence intervals or independent host attestations.",
            "Improved temporal mechanism expressivity does not establish task learning, NDU gain or negative-transfer safety.",
        ],
    }


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key in native CI measurement")
        result[name] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        measured = json.loads(
            args.matrix.read_bytes(), object_pairs_hook=no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("non-finite JSON number in native CI measurement")
            ),
        )
        summary = analyze(measured)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED_MECHANISM_COST_AUDIT", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
