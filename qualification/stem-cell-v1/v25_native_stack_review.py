"""Independent source-bound V25 Rust tile audit: NO model/authority promotion.

Imports only the frozen V24 *reviewer*, not any V25 producer/Rust code. Validates
actual original mmBERT feature and saved V16 Head bytes, standalone V24 and V25
Rust outputs, full per-process timing samples and fail-closed model lineage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import v24_rust_original_review as original

SIZES = (64, 256, 1024, 4096)
V24_SCHEMA = "hepta.stem.v24.rust-packed-worker-shadow.research"
V25_SCHEMA = "hepta.stem.v25.rust-stack-tile-worker-shadow.research"
SCHEMA = "hepta.stem.v25.original-rust-stack-tile.independent-review"
HALT = "HOLD_NATIVE_RESEARCH_NO_Q24_OR_FUTURE_OWNER_EVIDENCE"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def numbers(obj, prefix):
    result = {}
    for key in ("scalar_full", "packed_full", "packed_active32"):
        samples = obj[f"{key}_wall_samples_ns"]
        quantile = original.quantile(samples, .99)
        report_key = {
            "scalar_full": "scalar_p99_ms",
            "packed_full": "packed_p99_ms",
            "packed_active32": "active32_p99_ms",
        }[key]
        require(type(obj[report_key]) in (float, int)
                and np.isfinite(obj[report_key])
                and abs(obj[report_key] - quantile) <= 1e-6,
                "unfounded or forged native p99")
        result[key] = {"p99_ms": quantile,
                       "p95_ms": original.quantile(samples, .95),
                       "samples": len(samples)}
    return result


def require_common(obj, slots, mean_sha, schema):
    require(obj["schema"] == schema
        and obj["authority"] == "DENY_ALL"
        and obj["production_authorized"] is False
        and obj["rust_source_input_is_signature_authenticated"] is False
        and obj["worker_model_driver_integrated"] is False
        and obj["q24_policy_parity_verified"] is False
        and obj["original_encoder_forward_count"] == 0
        and obj["future_source_count"] == 0
        and obj["original_pretrained_cell_skills"] == 2
        and obj["physically_allocated_head_slots"] == slots
        and obj["logical_active_heads"] == 32
        and obj["feature_width"] == 384
        and obj["original_train_probes"] == 4
        and obj["source_feature_sha256"] == original.SRC_SHA
        and obj["v16_model_sha256"] == original.MODEL_SHA
        and obj["v15_mean_sha256"] == mean_sha
        and [obj[f"research_{x}"] for x in ("generation", "fence", "epoch", "scope", "principal", "purpose")]
               == [11, 17, 23, 29, 31, 37]
        and obj["allocated_head_weight_bytes"] == slots * 1540 * 4
        and obj["selected_cache_head_weight_bytes"] == 32 * 1540 * 4
        and obj["shared_feature_bytes"] == 4 * 384 * 4
        and obj["timed_rounds"] == 128 and obj["warmups"] == 8
        and obj["comparison_only_accumulation"] == "f64-of-original-f32"
        and type(obj["max_reference_packed_logit_abs_error"]) in (int, float)
        and obj["max_reference_packed_logit_abs_error"] == 0
        and type(obj["rolling_consumed_output"]) in (float, int)
        and np.isfinite(obj["rolling_consumed_output"]),
        "Rust source/model/authority/shape/counter mismatch")
    for k in ("whole_process_rss_after_bank_bytes", "whole_process_peak_rss_bytes"):
        value = obj[k]
        require(value is None or (type(value) is int and 0 < value < 1 << 37),
                "invalid process RSS")
    if obj["whole_process_peak_rss_bytes"] is not None and obj["whole_process_rss_after_bank_bytes"] is not None:
        require(obj["whole_process_peak_rss_bytes"] >= obj["whole_process_rss_after_bank_bytes"],
                "inconsistent peak RSS")
    return numbers(obj, "observed")


def read_proof(path, slots, expected, *, schema):
    raw = original.bounded(path, 4 * 4 * slots * 4 + 4)
    require(len(raw) == 4 * 4 * slots * 4, "truncated or padded native result")
    values = np.frombuffer(raw, dtype="<f4").reshape((4, slots, 4))
    require(np.isfinite(values).all(), "non-finite native output")
    maximum = float(np.abs(values.astype(np.float64) - expected.astype(np.float64)).max())
    require(maximum <= 2e-6 and np.array_equal(values.argmax(2), expected.argmax(2)),
            "original frozen model output differs from independent NumPy")
    return raw, maximum


def review(inputs: Path, v15: Path, v16: Path, root: Path):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "bounded true output directory required")
    original_features, original_split, mean_sha = original.read_original(inputs, v15, v16)
    manifest = original.read_json(root / "source-manifest.json")
    require(manifest["schema"] == "hepta.stem.v24.original-frozen-rust-wire.research"
         and manifest["source_feature_sha256"] == original.SRC_SHA
         and manifest["source_input_sha256"] == original.INPUT_SHA
         and manifest["original_saved_model_sha256"] == original.MODEL_SHA
         and manifest["v15_normalizer_sha256"] == mean_sha
         and manifest["slots"] == list(SIZES)
         and manifest["two_original_trained_head_values_replicated"] is True
         and manifest["production_authorized"] is False
         and manifest["rust_worker_driver_integrated"] is False
         and manifest["q24_parity_qualified"] is False,
         "private original SHA-bound frames inconsistent")

    observations = {"A": {}, "B": {}}
    for n in SIZES:
        wire = original.bounded(root / f"frame-{n}.bin", 32 * 1024)
        require(sha(wire) == manifest[f"frame_sha256_{n}"], "frozen private frame digest changed")
        original.validate_wire(wire, original_features, original_split, mean_sha, n)
        expected = original.independent_logits(original_features, original_split, n)
        for trial in ("A", "B"):
            results = {}
            for tag, schema in (("v24", V24_SCHEMA), ("v25", V25_SCHEMA)):
                obj = original.read_json(root / f"{tag}-{trial}-rust-report-{n}.json")
                stats = require_common(obj, n, mean_sha, schema)
                if tag == "v25":
                    require(obj["stack_tile_scratch_bytes"] == 512
                       and obj["tile_heap_scratch_buffers_per_invocation"] == 0
                       and obj["tile_width"] == 16
                       and obj["measured_hardware_memory_bandwidth"] is False
                       and obj["production_q24_backend_executed"] is False,
                       "invalid fused stack-tile claim")
                raw, diff = read_proof(root / f"{tag}-{trial}-rust-logits-{n}.bin", n, expected, schema=schema)
                results[tag] = {"numeric_max_error": diff,
                    "native_output_sha256": sha(raw), "p99_ms": stats["packed_full"]["p99_ms"],
                    "p95_ms": stats["packed_full"]["p95_ms"],
                    "scalar_p99_ms": stats["scalar_full"]["p99_ms"],
                    "active32_p99_ms": stats["packed_active32"]["p99_ms"],
                    "rss_peak_bytes": obj["whole_process_peak_rss_bytes"],
                    "timed_rounds_per_kernel": stats["packed_full"]["samples"]}
            require(results["v24"]["native_output_sha256"] == results["v25"]["native_output_sha256"],
                    "new stack-fused kernel changed original physical model output bytes")
            observations[trial][str(n)] = results
    return {"schema": SCHEMA, "decision": HALT,
        "source_feature_sha256": original.SRC_SHA,
        "original_v16_model_sha256": original.MODEL_SHA,
        "physical_trained_independent_head_values": 2,
        "fresh_pretrained_encoder_forwards": 0,
        "independent_future_case_roots": 0,
        "production_authorized": False,
        "q24_policy_parity_verified": False,
        "worker_execution_owner_integrated": False,
        "target_host_resource_qualified": False,
        "hardware_memory_bandwidth_attested": False,
        "cross_order_cpu_runs": ["A:V24 then V25", "B:V25 then V24"],
        "comparisons": observations,
        "semantic_model_advantage_verified": False,
        "v25_native_rust_execution_and_original_numeric_replay_verified": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--v15", type=Path, required=True)
    p.add_argument("--v16", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = review(args.inputs, args.v15, args.v16, args.root)
    if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
        raise ValueError("create-only verified audit destination required")
    with args.output.open("xb") as f:
        f.write(original.canonical(result))
        f.flush()


if __name__ == "__main__":
    main()
