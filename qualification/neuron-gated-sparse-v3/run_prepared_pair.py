#!/usr/bin/env python3
"""Pair fresh-process legacy vs prepared Q24 kernel probes, WITHOUT promotion.

This compares **only** five untrained deterministic mechanisms; the selected
encoder, full model weights, trusted host, complete WAL/CAS costs, statistical
confidence and actual NDU learning benefits are NOT measured.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from run_shadow_probe_matrix import ARMS, SCALES, validate_probe

SCHEMA = "hepta.neuron.prepared-paired-mechanism-only.v1"
MODES = ("legacy", "prepared")
MAX_EVENTS = 1024
MAX_PROBE_BINARY_BYTES = 1024 * 1024 * 1024
MAX_NATIVE_RECEIPT_JSON_BYTES = 128 * 1024


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha256_binary(binary: Path) -> str:
    """Hash the actual runner executable, never infer source provenance."""
    size = binary.stat().st_size
    require(0 < size <= MAX_PROBE_BINARY_BYTES, "missing or unbounded native binary")
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key in native observed receipt")
        result[key] = value
    return result


def reject_nonfinite_number(value: str) -> None:
    raise ValueError(f"nonfinite JSON number in native observed receipt: {value}")


def parse_native_receipt(raw: str) -> dict[str, Any]:
    require(len(raw.encode("utf-8")) <= MAX_NATIVE_RECEIPT_JSON_BYTES,
            "unbounded native receipt output")
    try:
        observed = json.loads(raw, object_pairs_hook=unique_json_keys,
                              parse_constant=reject_nonfinite_number)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid native JSON receipt") from exc
    require(isinstance(observed, dict), "native receipt must be one JSON object")
    return observed


def receipt_sha256(value: dict[str, Any]) -> str:
    """Canonicalize locally recorded JSON only; NOT a host signature."""
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def measured_ratio(a: int, b: int) -> str:
    require(type(a) is int and type(b) is int and a > 0 and b > 0,
            "invalid exact positive measured cost")
    return str((Decimal(a) / Decimal(b)).quantize(Decimal("0.000001")))


def validate_pair(
    records: dict[str, dict[str, Any]], arm: str, cells: int, digest: str, events: int,
) -> dict[str, Any]:
    require(set(records) == set(MODES), "both fresh-process modes required")
    for mode in MODES:
        value = records[mode]
        require(value.get("execution_mode") == mode, "probe reported a different execution mode")
        validate_probe(value, arm=arm, cells=cells, digest=digest, events=events)
        require(value.get("single_selected_config_resident") is True,
                "fixture process must hold only its selected model")
        require(value.get("simultaneous_legacy_and_prepared_config_resident") is False,
                "fixture process must never hold both model modes")
        require(type(value.get("model_config_setup_micros")) is int
                and value["model_config_setup_micros"] >= 0,
                "missing observed model config setup duration")
        require(value.get("all_model_parameter_budgets_matched") is False,
                "untrained probe cannot claim complete trained parameter parity")
        for field in (
            "p99_tick_nanos",
            "process_wall_micros",
            "process_peak_rss_bytes",
            "mechanism_tick_throughput_per_second_milli",
        ):
            require(type(value.get(field)) is int and value[field] > 0,
                    f"{field}: missing physical process measurement")
    old, new = records["legacy"], records["prepared"]
    require(old["width"] == new["width"] and type(old["width"]) is int,
            "mismatched temporal/activation width")
    require(old["frontier_digest"] == new["frontier_digest"],
            "prepared path changed exact checkpoint frontier")
    return {
        "arm": arm,
        "cells": cells,
        "events": events,
        "trace_sha256": digest,
        "exact_checkpoint_frontier_parity": True,
        "checkpoint_frontier_sha256": old["frontier_digest"],
        "legacy_p99_tick_nanos": old["p99_tick_nanos"],
        "prepared_p99_tick_nanos": new["p99_tick_nanos"],
        "legacy_to_prepared_p99_ratio": measured_ratio(
            old["p99_tick_nanos"], new["p99_tick_nanos"]
        ),
        "legacy_peak_rss_bytes": old["process_peak_rss_bytes"],
        "prepared_peak_rss_bytes": new["process_peak_rss_bytes"],
        "legacy_to_prepared_rss_ratio": measured_ratio(
            old["process_peak_rss_bytes"], new["process_peak_rss_bytes"]
        ),
        "legacy_to_prepared_throughput_ratio": measured_ratio(
            new["mechanism_tick_throughput_per_second_milli"],
            old["mechanism_tick_throughput_per_second_milli"]
        ),
        "legacy_wall_micros": old["process_wall_micros"],
        "prepared_wall_micros": new["process_wall_micros"],
        "legacy_model_config_setup_micros": old["model_config_setup_micros"],
        "prepared_model_config_setup_micros": new["model_config_setup_micros"],
        "separate_mode_config_residency": True,
        "raw_mode_receipts": {mode: records[mode] for mode in MODES},
        "raw_mode_receipt_sha256": {
            mode: receipt_sha256(records[mode]) for mode in MODES
        },
    }


def read_trace(trace_file: Path) -> tuple[str, int]:
    raw = trace_file.read_bytes()
    trace = json.loads(raw)
    require(isinstance(trace, dict)
            and trace.get("schema") == "hepta.neuron.mechanism-probe-trace.q24.v1",
            "unknown native Q24 trace schema")
    events = trace.get("events")
    require(isinstance(events, list) and 1 <= len(events) <= MAX_EVENTS,
            "invalid bounded trace event count")
    return hashlib.sha256(raw).hexdigest(), len(events)


def run(binary: Path, trace: Path, *, order_offset: int = 0) -> dict[str, Any]:
    require(type(order_offset) is int and order_offset in (0, 1),
            "only preregistered alternating process ordering is allowed")
    require(binary.is_file() and trace.is_file(), "missing binary or raw fixture trace")
    binary_sha256 = sha256_binary(binary)
    trace_sha256, event_count = read_trace(trace)
    pairs = []
    for scale_index, cells in enumerate(SCALES):
        for arm_index, arm in enumerate(ARMS):
            results: dict[str, dict[str, Any]] = {}
            modes = (MODES if (scale_index + arm_index + order_offset) % 2 == 0
                     else tuple(reversed(MODES)))
            for mode in modes:
                args = [
                    str(binary.resolve()), "--arm", arm, "--cells", str(cells),
                    "--mode", mode, "--trace", str(trace.resolve()),
                ]
                child = subprocess.run(args, capture_output=True, text=True, check=False, timeout=180)
                require(child.returncode == 0,
                        f"{arm} {cells} {mode}: native child rejected: {child.stderr[-800:]}")
                result = parse_native_receipt(child.stdout)
                require(isinstance(result, dict) and result.get("execution_mode") == mode,
                        f"{arm} {cells} {mode}: missing observed mode")
                results[mode] = result
            pairs.append(validate_pair(results, arm, cells, trace_sha256, event_count))
    require(len(pairs) == len(ARMS) * len(SCALES), "paired native matrix incomplete")
    require(sha256_binary(binary) == binary_sha256,
            "native executable changed during 40-process comparison")
    require(read_trace(trace) == (trace_sha256, event_count),
            "original Q24 trace changed during 40-process comparison")
    return {
        "schema": SCHEMA,
        "evidence_kind": "UNVERIFIED_HOST_UNTRAINED_KERNEL_ONLY",
        "source_trace_sha256": trace_sha256,
        "source_binary_sha256_claim": binary_sha256,
        "source_binary_independently_attested": False,
        "arms": list(ARMS),
        "scales": list(SCALES),
        "pair_count": len(pairs),
        "native_subprocess_count": 2 * len(pairs),
        "hosted_ci_run_id_claim": os.environ.get("GITHUB_RUN_ID", ""),
        "pairs": pairs,
        "private_model_parameter_budgets_matched": False,
        "real_training_or_model_efficacy": False,
        "real_encoder_model_batch_queue_wal_cas_cost": False,
        "target_host_certified": False,
        "ndu_eligible": False,
        "production_qualification": False,
        "decision": "NO_PROMOTION",
        "limitations": [
            "One alternating-order pair per arm/scale gives no uncertainty interval or causal gain.",
            "Both modes use synthetic untrained tensors, shared fixture input, 8 Tick events per Cell.",
            "The process includes Rust, journal-free checkpoint computations and one selected model config, not full model execution.",
            "Each fresh process constructs exactly one selected config before the Tick timer; cold setup micros is reported separately.",
            "Linux process VmHWM still includes allocator, executable and checkpoint memory; it is not isolated tensor-only RSS.",
            "The runner does not verify a trusted target host, production artifact signatures, independent training or future utility.",
            "All 40 raw mode receipts are retained with locally calculated digests and executable SHA; neither constitutes independent signing or execution attestation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = run(args.binary, args.trace)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED_PREPARED_PAIRED_PROBE", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
