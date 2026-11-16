"""Measure real private-head dispatch separately from learned task diversity.

Encoder measurements must come from an upstream observed receipt. This probe
never invents Encoder timings, energy use, task accuracy, or unmeasured bytes.
The JSON CLI plan binds a feature archive by SHA256 and loads trained artifacts.
"""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from cell_batch_runtime import BatchedCellRuntime, _digest, _integer
from cell_learning_models import NumpyCellHead
from cell_training_queue import TrainingQueue


def _samples(values):
    return {"samples_ns": values, "sample_count": len(values),
            "p50_ns": float(np.quantile(values, 0.50)),
            "p95_ns": float(np.quantile(values, 0.95)),
            "quantile_method": "linear; descriptive finite sample"}


def _rss():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _encoder_receipt(receipt, identity):
    if receipt is None:
        return None
    if (type(receipt) is not dict or receipt.get("feature_identity") != identity
            or receipt.get("observation_kind") != "measured"):
        raise ValueError("Encoder receipt must bind the feature identity and measurement")
    for name in ("physical_forward_calls", "encoder_instances"):
        _integer(receipt.get(name), 1, 2**63 - 1)
    for name in ("wall_ns", "cpu_ns", "model_parameter_bytes", "modality_parameter_bytes"):
        if receipt.get(name) is not None:
            _integer(receipt[name], 0, 2**63 - 1)
    return json.loads(json.dumps(receipt, allow_nan=False))


def measure_scale(heads, task_ids, features, source_digests, feature_identity, *,
                  generation=1, scales=(64, 256, 1024), repeats=20, top_k=16,
                  router_keys=None, relevant_task_ids=None, encoder_receipt=None,
                  source_paths=(), queue_report=None, cache_bytes=8 * 1024**2):
    """Use actual supplied weights; resident replicas do not add learned tasks.

    Router keys are one training-derived prototype per supplied head. Optional
    relevant_task_ids supplies a set of expected task IDs per feature row, so
    routing recall is reported independently of fraction of resident Cells used.
    """
    identity = _digest(feature_identity)
    repeats = _integer(repeats, 5, 1000)
    generation = _integer(generation, 1, 2**63 - 1)
    top_k = _integer(top_k, 1, 4096)
    _integer(cache_bytes, 0, 2**30)
    scales = tuple(_integer(n, 1, 4096) for n in scales)
    if not scales or len(set(scales)) != len(scales):
        raise ValueError("nonempty distinct scale values required")
    heads, task_ids = tuple(heads), tuple(task_ids)
    if not heads or len(heads) != len(task_ids) or min(scales) < len(heads):
        raise ValueError("each scale must retain all supplied trained heads")
    for head in heads:
        _integer(head.report.get("optimizer_steps"), 1, 5000)
        _integer(head.report.get("training_rows"), 1, 16384)
        if head.report.get("trained_tensor_sha256") != head.digest():
            raise ValueError("head parameters must match their completed training receipt")
        if getattr(head, "feature_identity", None) != identity:
            raise ValueError("scale evidence requires saved/loaded heads bound to this feature identity")
    x = np.asarray(features, dtype=np.float64)
    sources = tuple(source_digests)
    if x.ndim != 2 or not 1 <= len(x) <= 64 or len(x) != len(sources):
        raise ValueError("one to 64 source-bound feature rows required")
    keys = None if router_keys is None else np.asarray(router_keys, dtype=np.float64)
    if keys is not None and keys.shape != (len(heads), x.shape[1]):
        raise ValueError("one router prototype per supplied head required")
    relevant = None
    if relevant_task_ids is not None:
        relevant = [set(values) for values in relevant_task_ids]
        if (len(relevant) != len(x) or any(not v or not v <= set(task_ids) for v in relevant)):
            raise ValueError("nonempty known relevant task IDs required for every row")
    encoder = _encoder_receipt(encoder_receipt, identity)
    paths = {Path(p).resolve() for p in source_paths}
    if any(not path.is_file() for path in paths):
        raise ValueError("source accounting requires explicit files, not directories")
    storage = [{"path": str(p), "bytes": p.stat().st_size} for p in sorted(paths)]
    results = []
    for count in scales:
        indices = np.arange(count) % len(heads)
        resident = [heads[i] for i in indices]
        ids, tasks = [f"cell-{i:06d}" for i in range(count)], [task_ids[i] for i in indices]
        before_rss = _rss()
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        runtime = BatchedCellRuntime(resident, ids, tasks, identity, generation=generation,
                                    cache_bytes=cache_bytes,
                                    router_keys=None if keys is None else keys[indices])
        construction = {"wall_ns": time.perf_counter_ns() - began,
                        "cpu_ns": time.process_time_ns() - cpu,
                        "process_rss_before_bytes": before_rss,
                        "process_rss_after_bytes": _rss()}
        modes = [("all", count)]
        if keys is not None and top_k < count:
            modes.append(("selective", top_k))
        measurements = {}
        for name, k in modes:
            options = dict(source_digests=sources, feature_identity=identity,
                           generation=generation, top_k=k)
            warm = runtime.predict(x, **options)
            max_error = 0.0
            for row in range(len(x)):
                for column, index in enumerate(warm["selected_indices"][row]):
                    scalar = resident[index].predict_logits(x[row:row + 1])[0]
                    max_error = max(max_error, float(np.max(np.abs(scalar - warm["logits"][row, column]))))
            if max_error > 1e-9:
                raise ValueError("batched private heads differ from scalar predictions")
            observed = {key: [] for key in ("wall", "cpu", "cache", "router", "head")}
            before_count = runtime.accounting()
            for _ in range(repeats):
                began, cpu = time.perf_counter_ns(), time.process_time_ns()
                output = runtime.predict(x, **options)
                observed["wall"].append(time.perf_counter_ns() - began)
                observed["cpu"].append(time.process_time_ns() - cpu)
                for key in ("cache", "router", "head"):
                    observed[key].append(output[key + "_ns"])
            routed_tasks = [sorted({tasks[i] for i in row}) for row in output["selected_indices"]]
            recall = None if relevant is None else [len(set(got) & wanted) / len(wanted)
                                                   for got, wanted in zip(routed_tasks, relevant, strict=True)]
            measurements[name] = {"timing": {key: _samples(v) for key, v in observed.items()},
                "top_k": k, "activated_cell_fraction": k / count,
                "selected_cell_ids": output["selected_cell_ids"], "selected_task_ids": routed_tasks,
                "distinct_task_fraction_per_row": [len(row) / len(set(tasks)) for row in routed_tasks],
                "relevant_task_recall_per_row": recall,
                "mean_relevant_task_recall": None if recall is None else float(np.mean(recall)),
                "route_mode": output["route_mode"], "scalar_max_abs_error": max_error,
                "measured_head_evaluations": runtime.head_evaluations - before_count["head_evaluations"],
                "measured_array_batches": runtime.array_batches - before_count["head_array_batches"],
                "measured_dispatch_calls": runtime.dispatch_calls - before_count["dispatch_calls"],
                "encoder_calls_inside_dispatch": output["encoder_invocations_by_runtime"],
                "output_logits_bytes": output["logits"].nbytes,
                "process_rss_after_bytes": _rss()}
        accounting = runtime.accounting()
        ledger = {
            "shared_encoder": {"upstream_measured_receipt": encoder, "probe_owned_instances": 0},
            "modality_modules": {"parameter_bytes": None if encoder is None else encoder.get("modality_parameter_bytes")},
            "private_heads": {"tensor_bytes": runtime.parameter_bytes},
            "cache": {"tensor_bytes": runtime.cache.bytes, "capacity_bytes": cache_bytes,
                      "entry_count": len(runtime.cache._rows), "entry_capacity": runtime.cache.capacity_entries,
                      "python_metadata_bytes": None, "evictions": runtime.cache.evictions},
            "routing": {"prototype_tensor_bytes": accounting["router_tensor_bytes"],
                        "timings": "measurements.*.timing.router"},
            "training": {"queue_report": queue_report,
                         "source_head_reports": [h.report for h in heads]},
            "source_preservation": {"measured_files": storage,
                                    "measured_file_bytes": sum(v["bytes"] for v in storage) if storage else None,
                                    "completeness": "only explicitly supplied paths; not a total-storage claim"},
            "recovery": None if queue_report is None else queue_report.get("recovery"),
            "energy_joules": None}
        results.append({"resident_cells": count, "construction": construction,
                        "accounting": accounting, "measurements": measurements, "cost_ledger": ledger})
        del runtime, resident, warm, output
        gc.collect()
    return {"schema": "hepta.cell-scale-probe.v1", "feature_identity": identity,
            "generation": generation, "source_digests": sources, "feature_rows": len(x),
            "provided_head_count": len(heads), "declared_task_count": len(set(task_ids)),
            "task_count_is_caller_declared": True,
            "copies_are_independent_learning": False,
            "encoder_measurement_scope": "upstream receipt; no Encoder owned or invoked by this probe",
            "rss_scope": "whole current process on Linux, not isolated per category",
            "selective_routing_measured": keys is not None and any(top_k < n for n in scales),
            "task_accuracy_measured": False, "results": results}


def measure_queue(path, submissions, train, *, lease_ns=60_000_000_000):
    """Execute a real caller-supplied trainer, then verify durable publications.

    Payloads should reference immutable persisted inputs if another worker must
    resume training. The callback receives source/feature generation and lease.
    Callback execution is cooperative; expiry prevents publication, not CPU use.
    """
    if Path(path).exists():
        raise ValueError("queue measurement needs a fresh owned database path")
    submissions = tuple(submissions)
    _integer(len(submissions), 1, 1024)
    _integer(lease_ns, 1, 3_600_000_000_000)
    receipts, publications = [], []
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    with TrainingQueue(path, max_jobs=len(submissions)) as queue:
        for item in submissions:
            queue.submit(**item)
        while True:
            receipt = queue.run_one(train, lease_ns=lease_ns)
            if receipt is None:
                break
            receipts.append(receipt)
        for cell in sorted({item["cell_id"] for item in submissions}):
            publication = queue.read_current(cell)
            if publication is None:
                raise ValueError("current generation did not publish before its deadline")
            publications.append(publication)
        costs = queue.accounting()
    total = {"wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu}
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    with TrainingQueue(path, max_jobs=len(submissions)) as reopened:
        for publication in publications:
            if reopened.read_current(publication["cell_id"]) != publication:
                raise ValueError("publication did not survive reopening its database")
        reopened_costs = reopened.accounting()
    recovery = {"wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
                "verified_publications": len(publications), "fresh_connection": True,
                "fresh_process": False, "power_loss_tested": False}
    return {"training_receipts": receipts, "publication_digests": [p["result_sha256"] for p in publications],
            "total": total, "queue_costs_open": costs, "queue_costs_reopened": reopened_costs,
            "recovery": recovery}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.plan.stat().st_size > 1024**2:
        raise ValueError("oversized scale plan")
    plan = json.loads(args.plan.read_bytes())
    if plan["head_feature_identity"] != _digest(plan["feature_identity"]):
        raise ValueError("head and feature archives must use the same explicit identity pin")
    archive = Path(plan["arrays_npz"])
    if archive.stat().st_size > 128 * 1024**2:
        raise ValueError("oversized feature archive")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != _digest(plan["arrays_sha256"]):
        raise ValueError("feature archive changed")
    with zipfile.ZipFile(archive) as packed:
        if sum(v.file_size for v in packed.infolist()) > 256 * 1024**2:
            raise ValueError("decompressed feature archive exceeds bound")
    heads = [NumpyCellHead.load(v["path"], plan["head_feature_identity"]) for v in plan["heads"]]
    with np.load(archive, allow_pickle=False) as arrays:
        result = measure_scale(heads, [v["task_id"] for v in plan["heads"]],
            arrays["features"], plan["source_digests"], plan["feature_identity"],
            generation=plan.get("generation", 1), scales=plan.get("scales", [64, 256, 1024]),
            repeats=plan.get("repeats", 20), top_k=plan.get("top_k", 16),
            router_keys=arrays["router_keys"] if "router_keys" in arrays.files else None,
            relevant_task_ids=plan.get("relevant_task_ids"), encoder_receipt=plan.get("encoder_receipt"),
            source_paths=plan.get("source_paths", []))
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
