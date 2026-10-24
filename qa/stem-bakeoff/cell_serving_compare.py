"""Matched physical versus exact-state serving on frozen, calibrated Heads."""

import time

import numpy as np

from bounded_cell_runtime import BoundedCalibratedCellRuntime
from cell_batch_runtime import BatchedCellRuntime
from cell_calibration_bounded import apply_bounded_calibrator
from cell_runtime_bundle import array_digest


OUTPUT_ARRAYS = ("logits", "probabilities", "predictions", "served_mask",
                 "classification_accepted_mask", "positive_action_mask")


def output_digests(result):
    return {key: array_digest(result[key]) for key in OUTPUT_ARRAYS}


def _bindings(meta, head):
    return {"feature_identity": meta["feature_identity"], "predictor_sha256": head.digest(),
            "calibration_context_sha256": meta["calibration_context_sha256"]}


def build_cohorts(heads, fits, meta, count):
    if (type(count) is not int or not 1 <= count <= 1024 or len(heads) != len(fits)
            or not 1 <= len(heads) <= count):
        raise ValueError("bounded frozen serving cohort required")
    indices = np.arange(count) % len(heads)
    physical = [heads[i] for i in indices]
    calibrators = [fits[i] for i in indices]
    ids = [f"runtime-cell-{i}" for i in range(count)]
    tasks = [meta["task_id"]]*count
    setup, runtimes = {}, {}
    for kind in ("physical", "logical"):
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        if kind == "physical":
            runtime = BatchedCellRuntime(physical, ids, tasks, meta["feature_identity"],
                                         generation=meta["generation"])
        else:
            runtime = BoundedCalibratedCellRuntime(physical, calibrators, ids, tasks, meta["feature_identity"],
                expected_calibration_context_digests=[meta["calibration_context_sha256"]]*count,
                generation=meta["generation"], cache_bytes=64*heads[0].width*8)
        setup[kind] = {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu}
        runtimes[kind] = runtime
    reference, unique = runtimes["physical"], runtimes["logical"]
    if reference.parameter_bytes != count*heads[0].tensor_bytes:
        raise ValueError("physical reference must allocate every private parameter row")
    for name, array in reference._params.items():
        if any(np.shares_memory(array, head.params[name]) for head in heads):
            raise ValueError("reference parameters alias caller state")
        if np.shares_memory(array, unique.router.runtime._params[name]):
            raise ValueError("matched paths must own separate frozen parameter arrays")
    return unique, reference, indices, setup


def physical_prediction(runtime, x, sources, meta, fits, indices, expected_bindings):
    result = runtime.predict(x, source_digests=sources, feature_identity=meta["feature_identity"],
                             generation=meta["generation"])
    raw = result["logits"]
    result["raw_runtime_elapsed_ns"] = result.pop("elapsed_ns")
    probabilities = np.zeros_like(raw)
    began = time.perf_counter_ns()
    for state, (fitted, bindings) in enumerate(zip(fits, expected_bindings, strict=True)):
        columns = np.flatnonzero(indices == state)
        margins = (raw[:, columns, 1]-raw[:, columns, 0]).reshape(-1)
        # Group identical calibrators in both paths. All physical logits still
        # receive actual calibration; repeated validation is not the baseline.
        calibrated = np.empty((len(margins), 2), dtype=np.float64)
        for start in range(0, len(margins), 16384):
            calibrated[start:start+16384] = apply_bounded_calibrator(margins[start:start+16384], fitted,
                                                                  expected_bindings=bindings)
        probabilities[:, columns] = calibrated.reshape(len(x), len(columns), 2)
    served = np.ones(raw.shape[:2], dtype=bool)
    return {**result, "probabilities": probabilities, "served_mask": served,
        "predictions": probabilities.argmax(axis=2),
        "classification_accepted_mask": probabilities.max(axis=2) >= .7,
        "positive_action_mask": probabilities[:, :, 1] >= .7,
        "calibration_ns": time.perf_counter_ns()-began,
        "calibration_row_evaluations": len(x)*len(indices)}


def scalar_reference(heads, fits, meta, x):
    logits, probability = [], []
    for head, fit in zip(heads, fits, strict=True):
        raw = head.predict_logits(x)
        logits.append(raw)
        probability.append(apply_bounded_calibrator(raw[:, 1]-raw[:, 0], fit,
                           expected_bindings=_bindings(meta, head)))
    return np.stack(logits, axis=1), np.stack(probability, axis=1)


def _timed(call):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = call()
    return result, {"wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
        "internal_ns": {key: int(value) for key, value in result.items() if key.endswith("_ns")}}


def compare_condition(heads, fits, meta, x, sources, count, *, repetitions=7):
    if type(repetitions) is not int or not 1 <= repetitions <= 21:
        raise ValueError("bounded timing repetitions required")
    total, cpu = time.perf_counter_ns(), time.process_time_ns()
    runtime, reference, indices, setup = build_cohorts(heads, fits, meta, count)
    bindings = [_bindings(meta, head) for head in heads]
    identity, generation = meta["feature_identity"], meta["generation"]
    call = lambda: runtime.predict(x, source_digests=sources, feature_identity=identity, generation=generation)
    baseline = lambda: physical_prediction(reference, x, sources, meta, fits, indices, bindings)
    warmup = {}
    for name, fn in (("physical", baseline), ("logical", call)):
        _, warmup[name] = _timed(fn)
    timings, digest_records = {"physical": [], "logical": []}, []
    for repeat in range(repetitions):
        results = {}
        order = ("physical", "logical") if repeat % 2 == 0 else ("logical", "physical")
        for name in order:
            results[name], timing = _timed(baseline if name == "physical" else call)
            timings[name].append(timing)
        for key in OUTPUT_ARRAYS:
            if not np.array_equal(results["physical"][key], results["logical"][key]):
                raise ValueError(f"logical and physical {key} differ bitwise")
        digest_records.append(output_digests(results["logical"]))
    full = results["logical"]
    scalar, scalar_cost = _timed(lambda: dict(zip(("logits", "probabilities"), scalar_reference(heads, fits, meta, x))))
    maximum_logits = float(np.max(np.abs(full["logits"]-scalar["logits"][:, indices])))
    maximum_probability = float(np.max(np.abs(full["probabilities"]-scalar["probabilities"][:, indices])))
    if maximum_logits > 1e-9 or maximum_probability > 1e-12:
        raise ValueError("independent scalar path exceeds frozen absolute parity limits")
    expected = scalar["probabilities"][:, indices]
    decisions = {"predictions": expected.argmax(axis=2),
        "classification_accepted_mask": expected.max(axis=2) >= .7,
        "positive_action_mask": expected[:, :, 1] >= .7}
    if any(not np.array_equal(full[key], value) for key, value in decisions.items()):
        raise ValueError("scalar path changes a frozen probability decision")
    cached, cache_cost = _timed(lambda: runtime.predict_cached(sources,
        feature_identity=identity, generation=generation))
    if output_digests(cached) != output_digests(full):
        raise ValueError("cached source replay changes output")
    logical_count = len(runtime.logical_task_ids)
    scores = np.broadcast_to(np.arange(logical_count, 0, -1, dtype=np.float64), (len(x), logical_count))
    selected, route_cost = _timed(lambda: runtime.predict(x, source_digests=sources,
        feature_identity=identity, generation=generation, top_k=min(3, logical_count), router_scores=scores))
    served = selected["served_mask"]
    expected_indices = np.broadcast_to(np.arange(min(3, logical_count)), (len(x), min(3, logical_count)))
    expected_served = np.broadcast_to(runtime.router.physical_to_logical < min(3, logical_count), served.shape)
    if (not np.array_equal(selected["selected_logical_indices"], expected_indices)
            or not np.array_equal(served, expected_served)
            or not np.array_equal(selected["probabilities"][served], full["probabilities"][served])
            or np.any(selected["probabilities"][~served]) or np.any(selected["positive_action_mask"][~served])
            or np.any(selected["classification_accepted_mask"][~served])
            or np.any(selected["predictions"][~served] != -1)):
        raise ValueError("selective dispatch changes served output or fills unserved slots")
    if (full["head_evaluations"] != len(x)*logical_count
            or selected["head_evaluations"] != len(x)*min(3, logical_count)
            or reference.accounting()["private_parameter_tensor_bytes"] != count*heads[0].tensor_bytes):
        raise ValueError("observed physical and logical work counts differ")
    samples = {k: [v["wall_ns"] for v in values] for k, values in timings.items()}
    return {"mode": heads[0].mode, "batch_rows": len(x), "physical_cells": count,
        "declared_tasks": 1, "frozen_states": len(heads), "logical_states": logical_count,
        "setup": setup, "warmup": warmup, "timing_samples": timings,
        "p50_ns": {k: float(np.median(v)) for k, v in samples.items()},
        "p95_ns": {k: float(np.percentile(v, 95)) for k, v in samples.items()},
        "physical_accounting": reference.accounting(), "logical_accounting": runtime.accounting(),
        "caller_frozen_head_tensor_bytes": sum(h.tensor_bytes for h in heads),
        "physical_calibration_reference_records": len(fits),
        "physical_calibration_records_are_shared_inputs": True,
        "output_array_bytes": {k: int(full[k].nbytes) for k in OUTPUT_ARRAYS},
        "output_bytes_exclude_logical_intermediates_and_python_metadata": True,
        "bitwise_physical_logical": True, "max_scalar_logit_error": maximum_logits,
        "max_scalar_probability_error": maximum_probability, "scalar_decisions_equal": True,
        "scalar_cost": scalar_cost, "cached_call": cache_cost, "cached_equal": True,
        "cache_hits": runtime.router.runtime.cache.hits, "cache_misses": runtime.router.runtime.cache.misses,
        "top3_call": route_cost, "top3_served_predictions": int(served.sum()),
        "top3_head_evaluations": selected["head_evaluations"], "routing_quality_measured": False,
        "all_head_evaluations_per_call": full["head_evaluations"],
        "physical_head_evaluations_per_call": len(x)*count,
        "output_sha256_each_repeat": digest_records, "top3_output_sha256": output_digests(selected),
        "encoder_calls": 0, "parameter_updates": 0,
        "inclusive_condition": {"wall_ns": time.perf_counter_ns()-total, "cpu_ns": time.process_time_ns()-cpu,
            "scope": "setup, warmups, repeated predictions, parity, scalar, cache, routing and accounting; nested timings are included"}}
