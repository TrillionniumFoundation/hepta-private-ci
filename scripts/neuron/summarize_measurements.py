#!/usr/bin/env python3
"""Summarize executed native diagnostics, not projected performance or an SLA."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from typing import Any

PREFIX = "NEURON_V2_DIAGNOSTIC "

def percentile(values: list[int], fraction: float) -> int:
    if not values:
        raise ValueError("no observed samples")
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]

def summarize(samples: list[dict[str, Any]], expected_source: str, minimum: int = 64) -> dict[str, Any]:
    if len(expected_source) != 40 or any(c not in "0123456789abcdef" for c in expected_source):
        raise ValueError("exact source SHA is required")
    if len(samples) < minimum or len({s["sample"] for s in samples}) != len(samples):
        raise ValueError("too few observations or duplicate sample identities")
    binaries = {s["test_binary_digest"] for s in samples}
    if len(binaries) != 1 or len(next(iter(binaries))) != 64:
        raise ValueError("mixed or missing executable identity")
    latency: list[int] = []
    recovery: list[int] = []
    sync: list[int] = []
    growth: list[int] = []
    rss: list[int] = []
    for sample in samples:
        if sample["source_sha"] != expected_source or sample["schema"] != "hepta.neuron.diagnostic.v2":
            raise ValueError("source/schema mismatch")
        if sample["model_kind"] != "deterministic_fixture_not_production" or sample["qualification"] is not False:
            raise ValueError("diagnostics must not be relabelled as qualification")
        measurement = sample["measurement"]
        if measurement["returned_success"] is not True:
            raise ValueError("failed request cannot enter the successful diagnostic cohort")
        latency.append(measurement["total_micros"])
        recovery.append(sample["recovery_micros"])
        micros = 0
        bytes_added = 0
        for name, expected_calls in [("store", 2), ("index", 3)]:
            before, after = measurement[name + "_before"], measurement[name + "_after"]
            if after["io"]["sync_calls"] - before["io"]["sync_calls"] != expected_calls:
                raise ValueError("native sync boundary count mismatch")
            if after["io"]["sync_errors"] != before["io"]["sync_errors"]:
                raise ValueError("failed sync in successful cohort")
            micros += after["io"]["sync_micros"] - before["io"]["sync_micros"]
            if before["file_bytes"] is None or after["file_bytes"] is None:
                raise ValueError("unmeasured file size")
            bytes_added += after["file_bytes"] - before["file_bytes"]
        witness = measurement["witness_sync"]
        if witness is None or witness["sync_calls"] != 1 or witness["sync_errors"] != 0:
            raise ValueError("real witness measurement required")
        micros += witness["sync_micros"]
        if min(micros, bytes_added, latency[-1], recovery[-1]) < 0:
            raise ValueError("negative observation")
        sync.append(micros)
        growth.append(bytes_added)
        if sample["process_peak_rss_kib"] is not None:
            rss.append(sample["process_peak_rss_kib"])
    def quantiles(values: list[int]) -> dict[str, int]:
        return {name: percentile(values, fraction) for name, fraction in [("p50", .5), ("p95", .95), ("p99", .99)]}
    return {
        "schema": "hepta.neuron.diagnostic-summary.v2",
        "source_sha": expected_source,
        "test_binary_digest": next(iter(binaries)),
        "sample_count": len(samples),
        "quantile_method": "nearest_rank",
        "model_kind": "deterministic_fixture_not_production",
        "request_micros": quantiles(latency),
        "recovery_micros": quantiles(recovery),
        "summed_sync_micros_per_request": quantiles(sync),
        "generation_plus_index_growth_bytes": quantiles(growth),
        "process_high_water_rss_kib": max(rss) if rss else None,
        "rss_observed_samples": len(rss),
        "production_sla": False,
        "qualification": False,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples = [json.loads(line.split(PREFIX, 1)[1]) for line in args.log.read_text().splitlines() if PREFIX in line]
    args.output.write_text(json.dumps(summarize(samples, args.source_sha), indent=2) + "\n")

if __name__ == "__main__":
    main()
