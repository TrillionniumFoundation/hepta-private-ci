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


def basis_points(part: int, whole: int) -> int:
    if part < 0 or whole <= 0 or part > whole:
        raise ValueError("invalid phase share")
    return (part * 10_000 + whole // 2) // whole


def summarize(
    samples: list[dict[str, Any]], expected_source: str, minimum: int = 64
) -> dict[str, Any]:
    if len(expected_source) != 40 or any(
        character not in "0123456789abcdef" for character in expected_source
    ):
        raise ValueError("exact source SHA is required")
    if len(samples) < minimum or len({sample["sample"] for sample in samples}) != len(
        samples
    ):
        raise ValueError("too few observations or duplicate sample identities")
    binaries = {sample["test_binary_digest"] for sample in samples}
    if len(binaries) != 1 or len(next(iter(binaries))) != 64:
        raise ValueError("mixed or missing executable identity")

    latency: list[int] = []
    non_sync_latency: list[int] = []
    recovery: list[int] = []
    receipt_encode: list[int] = []
    full_receipt_materialize: list[int] = []
    receipt_encode_without_materialize: list[int] = []
    store_non_sync: list[int] = []
    index_non_sync: list[int] = []
    store_sync: list[int] = []
    index_sync: list[int] = []
    witness_sync: list[int] = []
    summed_sync: list[int] = []
    receipt_encode_share: list[int] = []
    full_receipt_materialize_share: list[int] = []
    store_sync_share: list[int] = []
    index_sync_share: list[int] = []
    witness_sync_share: list[int] = []
    summed_sync_share: list[int] = []
    store_growth: list[int] = []
    index_growth: list[int] = []
    combined_growth: list[int] = []
    rss: list[int] = []

    for sample in samples:
        if (
            sample["source_sha"] != expected_source
            or sample["schema"] != "hepta.neuron.diagnostic.v2"
        ):
            raise ValueError("source/schema mismatch")
        if (
            sample["model_kind"] != "deterministic_fixture_not_production"
            or sample["qualification"] is not False
        ):
            raise ValueError("diagnostics must not be relabelled as qualification")
        measurement = sample["measurement"]
        if measurement["returned_success"] is not True:
            raise ValueError("failed request cannot enter the successful diagnostic cohort")

        total_micros = measurement["total_micros"]
        encode_micros = measurement["receipt_encode_micros"]
        materialize_micros = measurement["full_receipt_materialize_micros"]
        store_commit_micros = measurement["store_commit_micros"]
        index_commit_micros = measurement["index_commit_micros"]
        if min(
            total_micros,
            encode_micros,
            materialize_micros,
            store_commit_micros,
            index_commit_micros,
        ) < 0 or materialize_micros > encode_micros:
            raise ValueError("invalid phase measurement")
        if max(encode_micros, store_commit_micros, index_commit_micros) > total_micros:
            raise ValueError("phase duration exceeds total request time")

        latency.append(total_micros)
        recovery.append(sample["recovery_micros"])
        receipt_encode.append(encode_micros)
        full_receipt_materialize.append(materialize_micros)
        receipt_encode_without_materialize.append(encode_micros - materialize_micros)
        phase_sync: dict[str, int] = {}
        phase_growth: dict[str, int] = {}
        for name, expected_calls in (("store", 2), ("index", 3)):
            before = measurement[name + "_before"]
            after = measurement[name + "_after"]
            calls = after["io"]["sync_calls"] - before["io"]["sync_calls"]
            errors = after["io"]["sync_errors"] - before["io"]["sync_errors"]
            micros = after["io"]["sync_micros"] - before["io"]["sync_micros"]
            if calls != expected_calls:
                raise ValueError("native sync boundary count mismatch")
            if errors != 0:
                raise ValueError("failed sync in successful cohort")
            if before["file_bytes"] is None or after["file_bytes"] is None:
                raise ValueError("unmeasured file size")
            growth = after["file_bytes"] - before["file_bytes"]
            if min(calls, errors, micros, growth) < 0:
                raise ValueError("negative observation")
            phase_sync[name] = micros
            phase_growth[name] = growth

        if phase_sync["store"] > store_commit_micros or phase_sync["index"] > index_commit_micros:
            raise ValueError("sync duration exceeds enclosing commit phase")
        store_non_sync.append(store_commit_micros - phase_sync["store"])
        index_non_sync.append(index_commit_micros - phase_sync["index"])

        witness = measurement["witness_sync"]
        if witness is None or witness["sync_calls"] != 1 or witness["sync_errors"] != 0:
            raise ValueError("real witness measurement required")
        if witness["sync_micros"] < 0:
            raise ValueError("negative observation")

        measured_sync = phase_sync["store"] + phase_sync["index"] + witness["sync_micros"]
        if min(total_micros, recovery[-1]) < 0 or measured_sync > total_micros:
            raise ValueError("invalid request or measured sync duration")
        store_sync.append(phase_sync["store"])
        index_sync.append(phase_sync["index"])
        witness_sync.append(witness["sync_micros"])
        summed_sync.append(measured_sync)
        non_sync_latency.append(total_micros - measured_sync)
        receipt_encode_share.append(basis_points(encode_micros, total_micros))
        full_receipt_materialize_share.append(
            basis_points(materialize_micros, total_micros)
        )
        store_sync_share.append(basis_points(phase_sync["store"], total_micros))
        index_sync_share.append(basis_points(phase_sync["index"], total_micros))
        witness_sync_share.append(basis_points(witness["sync_micros"], total_micros))
        summed_sync_share.append(basis_points(measured_sync, total_micros))
        store_growth.append(phase_growth["store"])
        index_growth.append(phase_growth["index"])
        combined_growth.append(phase_growth["store"] + phase_growth["index"])
        if sample["process_peak_rss_kib"] is not None:
            rss.append(sample["process_peak_rss_kib"])

    def quantiles(values: list[int]) -> dict[str, int]:
        return {
            name: percentile(values, fraction)
            for name, fraction in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99))
        }

    return {
        "schema": "hepta.neuron.diagnostic-summary.v2",
        "source_sha": expected_source,
        "test_binary_digest": next(iter(binaries)),
        "sample_count": len(samples),
        "quantile_method": "nearest_rank",
        "model_kind": "deterministic_fixture_not_production",
        "request_micros": quantiles(latency),
        "request_minus_measured_sync_micros": quantiles(non_sync_latency),
        "recovery_micros": quantiles(recovery),
        "receipt_encode_micros_per_request": quantiles(receipt_encode),
        "full_receipt_materialize_micros_per_request": quantiles(full_receipt_materialize),
        "receipt_encode_minus_materialize_micros_per_request": quantiles(
            receipt_encode_without_materialize
        ),
        "generation_store_non_sync_micros_per_request": quantiles(store_non_sync),
        "runtime_index_non_sync_micros_per_request": quantiles(index_non_sync),
        "store_sync_micros_per_request": quantiles(store_sync),
        "index_sync_micros_per_request": quantiles(index_sync),
        "witness_sync_micros_per_request": quantiles(witness_sync),
        "summed_sync_micros_per_request": quantiles(summed_sync),
        "phase_share_scale": "basis_points_of_request_total",
        "phase_shares_are_independent": True,
        "phase_share_basis_points": {
            "receipt_encode": quantiles(receipt_encode_share),
            "full_receipt_materialize": quantiles(full_receipt_materialize_share),
            "store_sync": quantiles(store_sync_share),
            "index_sync": quantiles(index_sync_share),
            "witness_sync": quantiles(witness_sync_share),
            "summed_sync": quantiles(summed_sync_share),
        },
        "generation_store_growth_bytes": quantiles(store_growth),
        "runtime_index_growth_bytes": quantiles(index_growth),
        "generation_plus_index_growth_bytes": quantiles(combined_growth),
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
    samples = [
        json.loads(line.split(PREFIX, 1)[1])
        for line in args.log.read_text().splitlines()
        if PREFIX in line
    ]
    args.output.write_text(
        json.dumps(summarize(samples, args.source_sha), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
