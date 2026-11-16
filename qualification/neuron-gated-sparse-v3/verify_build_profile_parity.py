#!/usr/bin/env python3
"""Independently compare DEBUG and RELEASE Q24 *fixture* runs, never select a Cell.

All 20 pairs must have identical trace, Cell count, logical input count and
exact checkpoint frontier. This guards accidental mixed-build reporting, not
pretrained-weight execution, whole-process optimization level, production
latency, signed host identity, learning efficacy, or final-use authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from analyze_mechanism_costs import analyze, no_duplicates, ratio
from run_shadow_probe_matrix import ARMS, SCALES

SCHEMA = "hepta.neuron.debug-release-mechanism-parity.v1"
MAX_BYTES = 4 * 1024 * 1024


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def read_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    """Open the same regular inode once; hash exactly the bytes we parse."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_BYTES,
                "unbounded/nonregular probe artifact")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            raw = os.read(fd, min(remaining, 128 * 1024))
            require(bool(raw), "short read of physical probe artifact")
            chunks.append(raw)
            remaining -= len(raw)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        require(all(getattr(before, f) == getattr(after, f) for f in fields),
                "changed physical probe artifact during read")
        source = b"".join(chunks)
    finally:
        os.close(fd)
    result = json.loads(
        source, object_pairs_hook=no_duplicates,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    require(type(result) is dict, "expected an exact JSON object")
    return result, hashlib.sha256(source).hexdigest()


def compare(debug: Any, release: Any) -> dict[str, Any]:
    # Reuse the original complete 5 x 4 matrix, positive-measurement, schema,
    # forbidden-authority and same-input validation, not a replacement parser.
    old = analyze(debug)
    new = analyze(release)
    require(old["original_trace_sha256"] == new["original_trace_sha256"],
            "DEBUG/RELEASE original input trace drift")
    require(old["events_per_cell"] == new["events_per_cell"],
            "DEBUG/RELEASE original number of events drift")
    left = {(r["arm"], r["cells"]): r for r in debug["results"]}
    right = {(r["arm"], r["cells"]): r for r in release["results"]}
    require(len(left) == 20 and len(right) == 20, "missing arm/Cell pair")
    comparisons: list[dict[str, Any]] = []
    for cells in SCALES:
        for arm in ARMS:
            a, b = left[arm, cells], right[arm, cells]
            require(a.get("compiler_debug_assertions_enabled") is True,
                    "DEBUG binary's compiled assertion mode is absent/false")
            require(b.get("compiler_debug_assertions_enabled") is False,
                    "RELEASE binary's compiled assertion mode is absent/true")
            for field in ("trace_sha256", "logical_tick_count", "width",
                          "frontier_digest", "temporal_parameter_count_only"):
                require(a.get(field) == b.get(field),
                        f"{arm}/{cells}: {field} changed between build profiles")
            require(type(a.get("width")) is int and 5 <= a["width"] <= 256,
                    "missing bounded native trace width")
            comparisons.append({
                "arm": arm,
                "cells": cells,
                "width": a["width"],
                "checkpoint_frontier_digest": a["frontier_digest"],
                "debug_p99_nanos": a["p99_tick_nanos"],
                "release_p99_nanos": b["p99_tick_nanos"],
                "release_over_debug_p99_ratio": ratio(
                    b["p99_tick_nanos"], a["p99_tick_nanos"]),
                "debug_tick_throughput_per_second_milli":
                    a["mechanism_tick_throughput_per_second_milli"],
                "release_tick_throughput_per_second_milli":
                    b["mechanism_tick_throughput_per_second_milli"],
                "release_over_debug_throughput_ratio": ratio(
                    b["mechanism_tick_throughput_per_second_milli"],
                    a["mechanism_tick_throughput_per_second_milli"]),
                "debug_peak_rss_bytes": a["process_peak_rss_bytes"],
                "release_peak_rss_bytes": b["process_peak_rss_bytes"],
            })
    return {
        "schema": SCHEMA,
        "decision": "NO_MODEL_PROMOTION",
        "evidence_kind": "UNTRAINED_KERNEL_FIXTURE_PROFILE_PARITY_ONLY",
        "input_trace_sha256": old["original_trace_sha256"],
        "events_per_cell": old["events_per_cell"],
        "profiles_compiled_debug_assertions_differ": True,
        "all_twenty_native_frontier_pairs_equal": True,
        "pair_count": len(comparisons),
        "pairs": comparisons,
        "full_model_parameter_budgets_matched": False,
        "same_source_native_binary_identity_independently_signed": False,
        "target_host_attested": False,
        "pretrained_encoder_executed": False,
        "learned_heads_or_future_quality_evaluated": False,
        "native_optimizer_flags_independently_attested": False,
        "whole_cell_latency_or_wal_recovery_measured": False,
        "ndu_eligible": False,
        "production_qualification": False,
        "warning": ("Debug-assertions compile flag is checked within both binaries; "
                    "actual cargo --release invocation is separately auditable in "
                    "the exact-source Actions job. Fixture-only measurements "
                    "cannot qualify a learned model, production host or NDU."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug-matrix", type=Path, required=True)
    parser.add_argument("--release-matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(args.debug_matrix.resolve() != args.release_matrix.resolve(),
                "DEBUG and RELEASE artifact must not be one input path")
        debug, left_hash = read_snapshot(args.debug_matrix)
        release, right_hash = read_snapshot(args.release_matrix)
        result = compare(debug, release)
        result["debug_matrix_file_sha256"] = left_hash
        result["release_matrix_file_sha256"] = right_hash
        # Never silently replace or rewrite a prior experiment report.
        with args.output.open("x", encoding="utf-8") as dest:
            json.dump(result, dest, sort_keys=True, indent=2, allow_nan=False)
            dest.write("\n")
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        print("BLOCKED_BUILD_PROFILE_PARITY: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
