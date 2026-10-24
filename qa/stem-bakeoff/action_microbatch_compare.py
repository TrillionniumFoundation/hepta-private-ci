"""Matched private Adam engineering work; one task may own many Cell states.

Saved checkpoints contain final private parameters, not resumable Adam state.
The fixed training-source probes establish recovery, never heldout task quality.
"""

import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_microbatch_training import FrozenTrainingBank, MicrobatchCellTrainer
from cell_runtime_bundle import check_npz

TOLERANCE = 1e-10
MAX_TENSOR_BYTES = 512 * 1024**2


def array_sha(value):
    value = np.asarray(value)
    return hashlib.sha256(canonical([list(value.shape), value.dtype.str]) + value.tobytes()).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def peak_rss():
    # This engineering probe is Linux-only; ru_maxrss is KiB on that platform.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def compare_condition(bank, labels, count, mode, *, steps=20, microbatch=8,
                      first="scalar", max_tensor_bytes=MAX_TENSOR_BYTES):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    y = np.asarray(labels)
    if (type(bank) is not FrozenTrainingBank or len(bank.task_ids) != 1
            or type(count) is not int or not 1 <= count <= 1024
            or mode not in ("linear", "gated", "residual")
            or first not in ("scalar", "batched")
            or type(steps) is not int or not 1 <= steps <= 20
            or type(microbatch) is not int or not 1 <= microbatch <= 8
            or y.shape != (bank._indices.shape[1],) or y.dtype.kind not in "iu"
            or set(y.tolist()) != {0, 1}):
        raise ValueError("one bounded binary training task and matched private work required")
    task = bank.task_ids[0]
    raw, width = bank.raw_rows(task), bank._raw.shape[1]
    private_labels = np.tile(y.astype(np.int64), (count, 1))
    setup, initial = {}, {}
    began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
    heads = [NumpyCellHead(width, 2, mode, rank=4, seed=1_000_000+i) for i in range(count)]
    for head in heads:
        head.feature_identity = bank.feature_identity
    initial["batched"] = [head.digest() for head in heads]
    caller_parameter_bytes = sum(head.tensor_bytes for head in heads)
    # Construct before either fit, so resource rejection cannot waste scalar updates.
    trainer = MicrobatchCellTrainer(heads, [f"cell-{i}" for i in range(count)],
        [task]*count, bank, microbatch=microbatch, max_tensor_bytes=max_tensor_bytes)
    setup["batched"] = {"wall_ns": time.perf_counter_ns()-began,
        "cpu_ns": time.process_time_ns()-began_cpu,
        "caller_initial_head_tensor_bytes": caller_parameter_bytes,
        "caller_initial_heads_released_before_fitting": True}
    del heads
    began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
    scalar = [NumpyCellHead(width, 2, mode, rank=4, seed=1_000_000+i) for i in range(count)]
    for head in scalar:
        head.feature_identity = bank.feature_identity
    initial["scalar"] = [head.digest() for head in scalar]
    setup["scalar"] = {"wall_ns": time.perf_counter_ns()-began,
                       "cpu_ns": time.process_time_ns()-began_cpu}
    if initial["scalar"] != initial["batched"] or len(set(initial["scalar"])) != count:
        raise ValueError("distinct private initial states must match between methods")
    states, executions = {}, {}
    probe_rows = sorted({0, len(raw)//2, len(raw)-1})
    representatives = sorted({0, count-1})
    scalar_probes = {}
    order = (first, "batched" if first == "scalar" else "scalar")
    for kind in order:
        began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
        if kind == "batched":
            fitted = trainer.train(private_labels, feature_identity=bank.feature_identity,
                                   generation=1, steps=steps)
            initial_loss, final_loss = fitted["initial_loss"], fitted["final_loss"]
            digests = fitted["trained_parameter_digests"]
            fit = {"wall_ns": time.perf_counter_ns()-began,
                   "cpu_ns": time.process_time_ns()-began_cpu}
            snapshot_at, snapshot_cpu = time.perf_counter_ns(), time.process_time_ns()
            states[kind] = trainer.parameters()
            accounting = {key: fitted[key] for key in ("parameter_bytes", "optimizer_state_bytes",
                "cached_feature_tensor_bytes", "transient_tensor_upper_bound_bytes",
                "total_tensor_upper_bound_bytes", "memory_bound_scope")}
            accounting.update(max_tensor_bytes=max_tensor_bytes,
                actual_parameter_bytes=sum(v.nbytes for v in trainer._params.values()),
                actual_moment_bytes=sum(v.nbytes for v in (*trainer._m.values(), *trainer._v.values())),
                private_label_tensor_bytes=private_labels.nbytes,
                moments_saved_for_restart=False)
            del trainer
        else:
            fits = [head.train(raw, y, steps=steps) for head in scalar]
            fit = {"wall_ns": time.perf_counter_ns()-began,
                   "cpu_ns": time.process_time_ns()-began_cpu}
            snapshot_at, snapshot_cpu = time.perf_counter_ns(), time.process_time_ns()
            initial_loss, final_loss = ([item[key] for item in fits]
                                       for key in ("initial_loss", "final_loss"))
            digests = [head.digest() for head in scalar]
            states[kind] = {name: np.stack([h.params[name] for h in scalar]) for name in scalar[0].params}
            scalar_probes = {str(i): scalar[i].predict_logits(raw[probe_rows]).tolist() for i in representatives}
            accounting = {"parameter_bytes": sum(h.tensor_bytes for h in scalar),
                "peak_one_head_optimizer_state_bytes": 2*scalar[0].tensor_bytes,
                "optimizer_retention": "scalar train discards moments after every completed Cell",
                "training_report_wall_ns_sum_nested": sum(v["wall_ns"] for v in fits),
                "training_report_cpu_ns_sum_nested": sum(v["cpu_ns"] for v in fits)}
            del scalar, fits
        executions[kind] = {"setup": setup[kind], "fit": fit,
            "snapshot_and_accounting": {"wall_ns": time.perf_counter_ns()-snapshot_at,
                "cpu_ns": time.process_time_ns()-snapshot_cpu},
            "initial_parameter_digests": initial[kind], "trained_parameter_digests": digests,
            "initial_loss": initial_loss, "final_loss": final_loss,
            "distinct_trained_private_states": len(set(digests)),
            "parameter_array_sha256": {k: array_sha(v) for k, v in states[kind].items()},
            "private_optimizer_updates": count*steps, "example_updates": count*steps*len(y),
            "accounting": accounting, "process_peak_rss_bytes_so_far": peak_rss()}
    parameter_difference = 0.0
    for name, expected in states["scalar"].items():
        actual = states["batched"][name]
        parameter_difference = max(parameter_difference, float(np.max(np.abs(expected-actual))))
        if not np.allclose(expected, actual, atol=TOLERANCE, rtol=TOLERANCE):
            raise ValueError("matched private parameter parity failed")
    loss_differences = {}
    for key in ("initial_loss", "final_loss"):
        a, b = (np.asarray(executions[kind][key]) for kind in ("scalar", "batched"))
        if not np.allclose(a, b, atol=TOLERANCE, rtol=TOLERANCE):
            raise ValueError("matched private loss parity failed")
        loss_differences[key] = float(np.max(np.abs(a-b)))
    result = {"schema": "hepta.action-private-adam-comparison.v1", "mode": mode,
        "width": width, "classes": 2, "rank": 4, "physical_cells": count,
        "task_id": task, "task_count": 1, "feature_identity": bank.feature_identity,
        "steps_per_cell": steps, "microbatch": microbatch, "learning_rate": .02, "l2": .001,
        "comparison_order": list(order), "initial_seed_range": [1_000_000, 1_000_000+count-1],
        "parameter_and_loss_atol": TOLERANCE, "parameter_and_loss_rtol": TOLERANCE,
        "maximum_absolute_parameter_difference": parameter_difference,
        "maximum_absolute_loss_difference": loss_differences,
        "parameters_bitwise_equal": all(np.array_equal(states["scalar"][k], v) for k, v in states["batched"].items()),
        "executions": executions, "recovery_probe_rows": probe_rows,
        "recovery_probe_features": raw[probe_rows].tolist(), "scalar_reference_logits": scalar_probes,
        "actual_total_private_optimizer_updates_both_methods": 2*count*steps,
        "actual_total_example_updates_both_methods": 2*count*steps*len(y),
        "encoder_forwards": 0, "encoder_updates": 0, "calibration_fit_calls": 0,
        "heldout_or_calibration_labels_used": False, "new_tasks_inferred_from_cell_count": False,
        "condition_wall_ns": time.perf_counter_ns()-started,
        "condition_cpu_ns": time.process_time_ns()-cpu,
        "condition_cost_scope": "both setups, private fits, snapshots and parity; excludes checkpoint save/recovery",
        "final_parameter_snapshot_bytes_at_parity": sum(v.nbytes for state in states.values() for v in state.values()),
        "memory_scope": "512MiB cap bounds only the batched trainer; scalar heads and the other method snapshot coexist for this comparison; process high-water is not isolated per method",
        "authority": "DENY_ALL", "quality_qualified": False}
    return result, states["batched"]


def save_checkpoint(root, result, state):
    expected = result["executions"]["batched"]["parameter_array_sha256"]
    if (set(state) != set(expected)
            or any(array_sha(value) != expected[name] for name, value in state.items())):
        raise ValueError("checkpoint parameters differ from the measured batched state")
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.absolute().parents)):
        raise ValueError("private checkpoint output cannot traverse symbolic links")
    root.mkdir(parents=True, exist_ok=False)
    with (root/"parameters.npz").open("xb") as stream:
        np.savez_compressed(stream, **state)
    metadata = {key: result[key] for key in ("mode", "width", "classes", "rank", "physical_cells",
        "task_id", "task_count", "feature_identity", "steps_per_cell", "initial_seed_range",
        "recovery_probe_rows", "recovery_probe_features", "scalar_reference_logits")}
    metadata.update(schema="hepta.action-private-parameter-checkpoint.v1",
        arrays={name: {"shape": list(value.shape), "dtype": value.dtype.str, "sha256": expected[name]}
                for name, value in state.items()},
        parameter_digests=result["executions"]["batched"]["trained_parameter_digests"],
        parameter_file_bytes=(root/"parameters.npz").stat().st_size,
        parameter_file_sha256=file_sha(root/"parameters.npz"), optimizer_restart_supported=False,
        authority="DENY_ALL", quality_qualified=False)
    write_json(root/"checkpoint.json", metadata)
    return file_sha(root/"checkpoint.json")


def verify_checkpoint(root, expected_manifest_sha256):
    root = Path(root)
    manifest, archive = root/"checkpoint.json", root/"parameters.npz"
    if (any(p.is_symlink() for p in (root, manifest, archive, *root.absolute().parents))
            or manifest.stat().st_size > 2*1024**2 or file_sha(manifest) != expected_manifest_sha256):
        raise ValueError("private checkpoint manifest identity differs")
    meta = json.loads(manifest.read_bytes())
    if (meta.get("schema") != "hepta.action-private-parameter-checkpoint.v1"
            or meta.get("authority") != "DENY_ALL" or meta.get("quality_qualified") is not False
            or meta.get("optimizer_restart_supported") is not False
            or type(meta.get("physical_cells")) is not int or not 1 <= meta["physical_cells"] <= 1024
            or meta.get("task_count") != 1 or meta.get("classes") != 2 or meta.get("rank") != 4
            or type(meta.get("width")) is not int or not 1 <= meta["width"] <= 4096
            or meta.get("mode") not in ("linear", "gated", "residual")
            or type(meta.get("parameter_digests")) is not list
            or len(meta["parameter_digests"]) != meta["physical_cells"]
            or set(meta["scalar_reference_logits"]) != {"0", str(meta["physical_cells"]-1)}
            or archive.stat().st_size > 128*1024**2
            or archive.stat().st_size != meta["parameter_file_bytes"]
            or file_sha(archive) != meta["parameter_file_sha256"]):
        raise ValueError("private checkpoint bytes or authority differs")
    head = NumpyCellHead(meta["width"], meta["classes"], meta["mode"], rank=meta["rank"])
    shapes = {name: ((meta["physical_cells"], *value.shape), np.float64) for name, value in head.params.items()}
    if sum(int(np.prod(shape))*8 for shape, _ in shapes.values()) > 128*1024**2:
        raise ValueError("private checkpoint decompression exceeds tensor budget")
    check_npz(archive, shapes)
    with np.load(archive, allow_pickle=False) as saved:
        if set(saved.files) != set(meta["arrays"]):
            raise ValueError("private checkpoint tensor names differ")
        state = {}
        for name in saved.files:
            value, pin = saved[name], meta["arrays"][name]
            if (list(value.shape) != pin["shape"] or value.dtype.str != pin["dtype"]
                    or array_sha(value) != pin["sha256"] or not np.isfinite(value).all()):
                raise ValueError("private checkpoint tensor identity differs")
            state[name] = value
    checks = []
    for index in range(meta["physical_cells"]):
        head.params = {name: array[index] for name, array in state.items()}
        if head.digest() != meta["parameter_digests"][index]:
            raise ValueError("recovered private Head digest differs")
        if str(index) not in meta["scalar_reference_logits"]:
            continue
        expected = meta["scalar_reference_logits"][str(index)]
        logits = head.predict_logits(np.asarray(meta["recovery_probe_features"]))
        if not np.allclose(logits, expected, atol=TOLERANCE, rtol=TOLERANCE):
            raise ValueError("recovered private Head differs from scalar training probe")
        checks.append({"cell_index": index, "tensor_sha256": head.digest(), "logits_sha256": array_sha(logits),
            "maximum_absolute_logit_difference": float(np.max(np.abs(logits-np.asarray(expected))))})
    return {"all_saved_arrays_verified": True, "all_cell_parameter_digests_verified": True,
            "verified_parameter_states": meta["physical_cells"], "restored_head_checks": checks,
            "checkpoint_manifest_sha256": expected_manifest_sha256,
            "optimizer_updates": 0, "encoder_forwards": 0, "quality_scoring": False}
