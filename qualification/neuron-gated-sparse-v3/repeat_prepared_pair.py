#!/usr/bin/env python3
"""Repeated A/B mechanism-only study; never a production/performance qualification.

Three or five independent *fresh-process* repetitions per 5-arm x 4-scale
setting. Alternate mode order per repetition; verify 40 raw receipts and
full frontier equality in every repetition. Ranges and medians are DESCRIPTIVE
and are neither a causal estimate, p99 confidence bound nor a host attestation.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import statistics
import sys
from typing import Any

import run_prepared_pair as paired
import verify_prepared_pair_report as verify

SCHEMA = "hepta.neuron.repeated-prepared-q24-fixture.v1"
ALLOWED_REPETITIONS = (3, 5)
RAW_RESULT_LIMIT = 5
MEASURES = (
    "legacy_p99_tick_nanos", "prepared_p99_tick_nanos",
    "legacy_peak_rss_bytes", "prepared_peak_rss_bytes",
    "legacy_wall_micros", "prepared_wall_micros",
    "legacy_model_config_setup_micros", "prepared_model_config_setup_micros",
)


def positive_decimal(raw: Any) -> Decimal:
    paired.require(isinstance(raw, str) and raw, "missing decimal ratio")
    try:
        value = Decimal(raw)
    except Exception as exc:
        raise ValueError("invalid decimal ratio") from exc
    paired.require(value.is_finite() and value > 0, "nonpositive or nonfinite ratio")
    return value


def describe(values: list[Decimal]) -> dict[str, str]:
    paired.require(len(values) in ALLOWED_REPETITIONS, "insufficient independent repetitions")
    paired.require(all(value.is_finite() and value >= 0 for value in values),
                   "nonfinite or negative observed measurement")
    return {
        "minimum": str(min(values)),
        "median": str(statistics.median(values)),
        "maximum": str(max(values)),
    }


def aggregate(reports: list[dict[str, Any]], *, binary: Path | None = None) -> dict[str, Any]:
    paired.require(len(reports) in ALLOWED_REPETITIONS, "three or five exact A/B repetitions required")
    paired.require(len(reports) <= RAW_RESULT_LIMIT, "unbounded repetition count")
    summaries = []
    first: dict[str, Any] | None = None
    for round_index, report in enumerate(reports):
        verification = verify.audit(report, binary=binary)
        if first is None:
            first = report
        else:
            for key in (
                "schema", "evidence_kind", "source_trace_sha256",
                "source_binary_sha256_claim", "arms", "scales",
                "native_subprocess_count", "pair_count",
            ):
                paired.require(report[key] == first[key],
                               f"repetition changed observed {key}")
        paired.require(verification["exact_checkpoint_frontier_pairs_rechecked"] == 20,
                       "some paired checkpoint comparisons not independently replayed")
        summaries.append(verification)
    assert first is not None
    rows = []
    for arm in paired.ARMS:
        for cells in paired.SCALES:
            samples = []
            for report in reports:
                matches = [
                    x for x in report["pairs"] if x["arm"] == arm and x["cells"] == cells
                ]
                paired.require(len(matches) == 1, "missing/duplicate repeated pair")
                samples.append(matches[0])
            frontier = samples[0]["checkpoint_frontier_sha256"]
            paired.require(all(x["checkpoint_frontier_sha256"] == frontier for x in samples),
                           "repetition changed Q24 checkpoint frontier")
            values = {}
            for key in MEASURES:
                vals = [x[key] for x in samples]
                paired.require(all(type(v) is int and v >= 0 for v in vals),
                               f"invalid physical {key}")
                values[key] = describe([Decimal(v) for v in vals])
            ratios = [
                positive_decimal(x["legacy_to_prepared_p99_ratio"]) for x in samples
            ]
            rss_ratios = [
                positive_decimal(x["legacy_to_prepared_rss_ratio"]) for x in samples
            ]
            throughput_ratios = [
                positive_decimal(x["legacy_to_prepared_throughput_ratio"]) for x in samples
            ]
            rows.append({
                "arm": arm,
                "cells": cells,
                "frontier_sha256": frontier,
                "repeat_count": len(samples),
                "p99_ratio_legacy_over_prepared": describe(ratios),
                "rss_ratio_legacy_over_prepared": describe(rss_ratios),
                "throughput_ratio_prepared_over_legacy": describe(throughput_ratios),
                "p99_prepared_faster_in_all_repeats": all(v > 1 for v in ratios),
                "descriptive_observed_measures": values,
                "per_repeat_raw_comparisons": samples,
            })
    return {
        "schema": SCHEMA,
        "type": "REPEATED_UNTRAINED_Q24_KERNEL_ONLY",
        "source_binary_sha256_claim": first["source_binary_sha256_claim"],
        "source_trace_sha256": first["source_trace_sha256"],
        "repetitions": len(reports),
        "arm_scale_pairs": len(rows),
        "original_raw_native_process_receipts": 40 * len(reports),
        "raw_round_reports": reports,
        "structural_round_audits": summaries,
        "comparisons": rows,
        "repetition_order": [
            "even rounds: original mode order by arm/scale",
            "odd rounds: swapped mode order by arm/scale",
        ],
        "qualified_ci_host": False,
        "real_training_or_model_efficacy": False,
        "full_model_budget_matched": False,
        "certified_p99_or_rss_improvement": False,
        "independent_ndu_or_signed_cas_verified": False,
        "production_qualification": False,
        "decision": "NO_PROMOTION",
        "limitations": [
            "Repeated hosted-runner observations are descriptive, not a causal experiment or confidence bound.",
            "Model setup is outside each timed Tick loop; it is recorded separately.",
            "All models and modes use synthetic untrained kernels, not full Encoder + Head inference.",
            "VmHWM includes process and checkpoint overhead, not just graph tensors.",
            "No independent target-host attestation, training fairness, future utility or final-use authority exists.",
        ],
    }


def run(binary: Path, trace: Path, repetitions: int) -> dict[str, Any]:
    paired.require(type(repetitions) is int and repetitions in ALLOWED_REPETITIONS,
                   "three or five independently paired repetitions required")
    report_rounds = []
    for index in range(repetitions):
        # Every paired.run invocation independently hashes binary/trace at both
        # ends and starts 40 fresh child processes. Swapping order by round
        # reduces, but cannot eliminate, temporal drift.
        report_rounds.append(paired.run(binary, trace, order_offset=index % 2))
    return aggregate(report_rounds, binary=binary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, choices=ALLOWED_REPETITIONS, default=3)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        output = run(args.binary, args.trace, args.repetitions)
    except (ValueError, OSError, TypeError, KeyError, OverflowError) as exc:
        print(json.dumps({"status": "BLOCKED_REPEATED_Q24_AB", "error": str(exc}),
              file=sys.stderr)
        return 2
    raw = json.dumps(output, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.write_text(raw, encoding="utf-8")
    else:
        print(raw, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
