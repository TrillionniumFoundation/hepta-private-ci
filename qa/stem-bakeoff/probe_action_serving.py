"""Execute the fixed 770D serving protocol without fitting or quality scoring."""

import argparse
import gc
import json
import os
from pathlib import Path
import resource
import time

import numpy as np

from bounded_cell_runtime import BoundedCalibratedCellRuntime
from cell_learning_models import canonical
from cell_runtime_bundle import MODES, array_digest, inventory, load_serving_inputs, load_states, sha_file
from cell_serving_compare import compare_condition, output_digests


CODE_FILES = ("probe_action_serving.py", "cell_serving_compare.py", "bounded_cell_runtime.py",
    "cell_runtime_bundle.py", "cell_batch_runtime.py", "cell_logical_routing.py",
    "cell_calibration_bounded.py", "cell_learning_models.py", "cell_learning_metrics.py",
    "CELL_RUNTIME_770_PROTOCOL.md")


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def code_pins():
    return {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}


def check_threads():
    if any(os.environ.get(key) != "1" for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("explicit one-thread BLAS environment required")


def replay(bundle, manifest_sha256):
    """Fresh-process numerical replay; no quality labels, fitting or scalar rerun."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    check_threads()
    pins = code_pins()
    meta, x, rows = load_serving_inputs(bundle, expected_manifest_sha256=manifest_sha256)
    sources = [r["source_record_digest"] for r in rows]
    results = {}
    for mode in MODES:
        heads, fits = load_states(bundle, meta, mode)
        indices = np.arange(1024) % len(heads)
        runtime = BoundedCalibratedCellRuntime([heads[i] for i in indices], [fits[i] for i in indices],
            [f"runtime-cell-{i}" for i in range(1024)], [meta["task_id"]]*1024, meta["feature_identity"],
            expected_calibration_context_digests=[meta["calibration_context_sha256"]]*1024,
            generation=meta["generation"], cache_bytes=64*770*8)
        args = {"feature_identity": meta["feature_identity"], "generation": meta["generation"]}
        full = runtime.predict(x, source_digests=sources, **args)
        cached = runtime.predict_cached(sources, **args)
        scores = np.broadcast_to(np.arange(9, 0, -1, dtype=np.float64), (64, 9))
        selected = runtime.predict(x, source_digests=sources, top_k=3, router_scores=scores, **args)
        if output_digests(full) != output_digests(cached):
            raise ValueError("restored cache differs from restored direct serving")
        results[mode] = {"full": output_digests(full), "top3": output_digests(selected),
                         "cache_equal": True, "accounting": runtime.accounting()}
    load_serving_inputs(bundle, expected_manifest_sha256=manifest_sha256)
    if code_pins() != pins:
        raise ValueError("replay implementation changed")
    return {"schema": "hepta.action-serving-replay.v1", "bundle_manifest_sha256": manifest_sha256,
        "source_code_sha256": pins, "modes": results, "physical_cells": 1024, "batch_rows": 64,
        "encoder_calls": 0, "parameter_updates": 0, "quality_labels_used": False,
        "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
        "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False}


def run_probe(bundle, output, *, manifest_sha256):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    check_threads()
    pins = code_pins()
    root = Path(output)
    if root.exists() or any(p.is_symlink() for p in (root.absolute(), *root.absolute().parents)):
        raise ValueError("new nonsymlink measurement root required")
    root.mkdir(parents=True)
    completed = []
    try:
        load_at, load_cpu = time.perf_counter_ns(), time.process_time_ns()
        meta, x, rows = load_serving_inputs(bundle, expected_manifest_sha256=manifest_sha256)
        load_cost = {"wall_ns": time.perf_counter_ns()-load_at, "cpu_ns": time.process_time_ns()-load_cpu}
        sources = [r["source_record_digest"] for r in rows]
        plan = {"schema": "hepta.action-serving-probe.v1", "bundle_manifest_sha256": manifest_sha256,
            "feature_identity": meta["feature_identity"], "task_id": meta["task_id"], "task_count": 1,
            "source_code_sha256": pins, "modes": list(MODES), "scales": [64, 256, 1024],
            "batch_rows": [1, 16, 64], "repetitions": 7, "warmups_per_path": 1,
            "feature_array_sha256": array_digest(x), "source_digests": sources,
            "selection": "all9 frozen states per mode; source-hash fixed first64 input prefixes",
            "scalar_absolute_limits": {"logits": 1e-9, "probabilities": 1e-12},
            "scalar_decisions_must_match": True, "logical_physical_must_match_bitwise": True,
            "classification_and_positive_action_threshold": .7, "routing": "fixed logical scores; top3; no relevance claim",
            "quality_labels_used": False, "quality_scoring_performed": False,
            "timing_scope": "shared CPU, outer calls include copies/guards; no isolated SLO or hardware claim"}
        write_json(root/"plan.json", plan)
        head_loads = {}
        for mode in MODES:
            load_at, load_cpu = time.perf_counter_ns(), time.process_time_ns()
            heads, fits = load_states(bundle, meta, mode)
            head_loads[mode] = {"wall_ns": time.perf_counter_ns()-load_at,
                "cpu_ns": time.process_time_ns()-load_cpu,
                "parameter_digests": [h.digest() for h in heads],
                "tensor_bytes": sum(h.tensor_bytes for h in heads)}
            for count in plan["scales"]:
                for batch in plan["batch_rows"]:
                    report = compare_condition(heads, fits, meta, x[:batch], sources[:batch], count)
                    report["process_lifetime_peak_rss_bytes_so_far"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
                    name = f"{mode}-{count}-{batch}.json"
                    write_json(root/name, report)
                    completed.append(report)
                    print(json.dumps({"mode": mode, "cells": count, "rows": batch,
                        "logical_p50_ms": report["p50_ns"]["logical"]/1e6,
                        "physical_p50_ms": report["p50_ns"]["physical"]/1e6}), flush=True)
                    gc.collect()
        load_serving_inputs(bundle, expected_manifest_sha256=manifest_sha256)
        if code_pins() != pins:
            raise ValueError("serving implementation changed during measurement")
        report = {"plan": plan, "input_load": load_cost, "head_loads": head_loads, "conditions": completed,
            "inclusive_probe": {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
                "scope": "all input/code checks, loading, setup, warmups, repeats, regression comparisons, routing/cache checks and condition writes; excludes final report/manifest writes; nested fields already included"},
            "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "encoder_calls": 0, "parameter_updates": 0, "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
            "quality_qualified": False, "native_production_integration_claimed": False}
        write_json(root/"report.json", report)
        write_json(root/"manifest.json", inventory(root))
        return report
    except Exception as error:
        write_json(root/"failed-attempt.json", {"error": repr(error), "completed_conditions": len(completed),
            "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
            "initial_code_sha256": pins, "partial_outputs_retained": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.replay:
        write_json(args.output, replay(args.bundle, args.manifest_sha256))
    else:
        run_probe(args.bundle, args.output, manifest_sha256=args.manifest_sha256)
