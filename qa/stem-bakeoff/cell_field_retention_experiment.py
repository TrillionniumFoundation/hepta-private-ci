"""Freeze all three actual-state retention arms and predictions before new scoring.

Each condition runs in a fresh, sequential CPU-only Python worker. Both the
unchanged quadratic policy and optional hinge policy use the same original
reference and information. This module has no final-label reader or fallback.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

from cell_field_control import Reference, build_reference
from cell_field_features import file_hash
from cell_field_retention_checkpoint import save_retention_run
from cell_field_retention_run import ARMS, RetentionRunError, RetentionRunLimits, run_retention_control
from cell_field_run import _deny_final_labels, _inputs, _project, _split_arrays
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


SCHEMA = "hepta.cell-retention.experiment.v1"
SOURCE_FILES = ("cell_field_retention_experiment.py", "cell_field_retention_run.py",
    "cell_field_retention_checkpoint.py", "cell_field_retention.py", "cell_field_control.py",
    "cell_field_state.py", "cell_field_run.py", "cell_field_replay.py", "cell_field_features.py",
    "cell_learning_models.py", "cell_learning_metrics.py")


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def _arrays(path, **values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **values)


def _code():
    return {name: file_hash(Path(__file__).with_name(name)) for name in SOURCE_FILES}


def _plan(path, expected):
    if file_hash(path) != expected:
        raise ValueError("explicit frozen experiment protocol hash differs")
    plan = json.loads(Path(path).read_bytes())
    if (plan.get("schema") != SCHEMA or plan.get("status") != "FROZEN"
            or plan.get("source_code_sha256") != _code()
            or plan.get("authority") != "DENY_ALL" or plan.get("production_activation_allowed") is not False
            or plan.get("policies") != list(ARMS) or plan.get("action_masks") != ["bias"]
            or plan.get("seeds") != [7, 17, 29] or plan.get("head_modes") != ["linear", "gated"]
            or plan.get("classes") != 4 or plan.get("horizon") != 24
            or plan.get("warmup_steps") != 64 or plan.get("projection", {}).get("width") != 8
            or plan.get("worker_wall_seconds") != 75 or plan.get("worker_cpu_seconds") != 15
            or plan.get("run_limits") != asdict(RetentionRunLimits())):
        raise ValueError("exact reviewed bounded three-arm experiment protocol required")
    return plan


def _rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _child_cpu_ns():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return int((value.ru_utime + value.ru_stime) * 1e9)


def worker(request, expected_request_sha256):
    """One trusted frozen local request; no user-supplied code or external effects."""
    sys.addaudithook(_deny_final_labels)
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    if file_hash(request) != expected_request_sha256:
        raise ValueError("worker request changed after publication")
    spec = json.loads(Path(request).read_bytes())
    root = Path(spec["run_root"])
    plan = _plan(root / "protocol.json", spec["protocol_sha256"])
    resource.setrlimit(resource.RLIMIT_CPU, (plan["worker_cpu_seconds"], plan["worker_cpu_seconds"]))
    if any(os.environ.get(name) != "1" for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("single-threaded numerical worker environment required")
    name = spec["run_id"]
    record = {"run_id": name, "arm": spec["arm"], "initial_index": spec["initial_index"],
              "seed": spec["seed"], "head": spec["head"], "status": "failed",
              "worker_pid": os.getpid(), "protocol_sha256": spec["protocol_sha256"]}
    try:
        state = CellTrainingState.load(root / spec["initial_path"], spec["bindings"],
            expected_protocol=plan["optimizer"], expected_contexts=spec["contexts"],
            expected_state_digest=spec["initial_state_sha256"])
        reference_path = root / spec["reference_path"]
        if file_hash(reference_path) != spec["reference_sha256"]:
            raise ValueError("shared original reference archive changed")
        with np.load(reference_path, allow_pickle=False) as values:
            ref = Reference(state.clone(), values["train_features"], values["train_labels"],
                ((values["probe_current_x"], values["probe_current_y"]),
                 (values["probe_old_x"], values["probe_old_y"])),
                values["reference_states"], values["reference_observations"], values["state_scales"],
                values["A"], values["C_extended"], plan["h"], [], 0)
        if (ref.horizon != plan["horizon"] or state.step_count != plan["warmup_steps"]
                or state.head.width != 8 or state.head.classes != 4
                or state.head.mode != spec["head"] or spec["seed"] not in plan["seeds"]):
            raise ValueError("worker checkpoint/reference dimensions differ from fixed census")
        kwargs = {"arm": spec["arm"], "anchor": float(ref.observations[0, 1]),
            "tolerance": plan["retention_tolerance"], "old_weight": plan["retention_weight"],
            "current_target": plan["current_target_displacement"], "effort_price": plan["effort_price"],
            "mask": "bias", "limits": RetentionRunLimits(**plan["run_limits"])}
        record["input_load_wall_ns"] = time.perf_counter_ns() - started
        record["input_load_cpu_ns"] = time.process_time_ns() - cpu_started
        try:
            result = run_retention_control(state, ref, **kwargs)
        except RetentionRunError as error:
            result = error.result
        record.update(status=result["receipt"]["status"], controller_receipt=result["receipt"],
                      costs=result["costs"], actual_state_sha256=result["state"].digest())
        record["checkpoint"] = save_retention_run(root / "conditions" / name, result)
        reload_wall, reload_cpu = time.perf_counter_ns(), time.process_time_ns()
        restored_state = CellTrainingState.load(root / "conditions" / name / "state", state.bindings,
            expected_protocol=state.protocol, expected_contexts=state.contexts,
            expected_state_digest=result["state"].digest())
        if not np.array_equal(restored_state.vector(), result["state"].vector()):
            raise ValueError("complete Adam checkpoint reload changed tensor bytes")
        record["complete_state_reload"] = {"bitwise_equal": True,
            "wall_ns": time.perf_counter_ns() - reload_wall, "cpu_ns": time.process_time_ns() - reload_cpu}
        if result["receipt"]["status"] == "completed":
            began, cpu = time.perf_counter_ns(), time.process_time_ns()
            features_path = root / "projected_features.npz"
            if file_hash(features_path) != spec["projected_features_sha256"]:
                raise ValueError("frozen projected prediction inputs changed")
            with np.load(features_path, allow_pickle=False) as values:
                projected = values["features"]
            if projected.shape != (480, 8) or projected.dtype != np.float64 or not np.isfinite(projected).all():
                raise ValueError("exact bounded frozen prediction matrix required")
            probabilities = result["state"].head.predict_proba(projected)
            head_path = root / "conditions" / name / "serving_head"
            result["state"].head.save(head_path, spec["feature_identity"])
            restored = NumpyCellHead.load(head_path, spec["feature_identity"])
            if not np.array_equal(probabilities, restored.predict_proba(projected)):
                raise ValueError("persisted serving head changed frozen predictions")
            _arrays(root / "conditions" / name / "predictions.npz", probabilities=probabilities)
            record.update(predictions_sha256=file_hash(root / "conditions" / name / "predictions.npz"),
                serving_roundtrip_equal=True, prediction_persistence_reload_wall_ns=time.perf_counter_ns() - began,
                prediction_persistence_reload_cpu_ns=time.process_time_ns() - cpu)
        else:
            record["failure"] = result["receipt"]["error"]
    except Exception as error:
        record.update(status="failed", failure={"type": type(error).__name__, "message": str(error)},
                      traceback=traceback.format_exc())
    record.update(worker_wall_ns=time.perf_counter_ns() - started,
                  worker_cpu_ns=time.process_time_ns() - cpu_started,
                  process_peak_rss_bytes=_rss_bytes(), child_process_cpu_ns=_child_cpu_ns(),
                  process_tree_scope="one fresh worker, no subprocesses invoked by condition code",
                  authority="DENY_ALL")
    _write(root / "worker_records" / f"{name}.json", record)
    print(json.dumps({"run_id": name, "status": record["status"], "costs": record.get("costs")}), flush=True)
    return record


def supervise(request, root, run_id, wall_seconds):
    """Fresh sequential worker; killed or missing receipt is an explicit failure."""
    logs = root / "worker_logs"
    logs.mkdir(parents=True, exist_ok=True)
    began, child_cpu = time.perf_counter_ns(), _child_cpu_ns()
    argv = [sys.executable, str(Path(__file__).resolve()), "worker", "--request", str(request),
            "--expected-request-sha256", file_hash(request)]
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "CUDA_VISIBLE_DEVICES": ""}
    timed_out = False
    with (logs / f"{run_id}.stdout").open("xb") as stdout, (logs / f"{run_id}.stderr").open("xb") as stderr:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=env)
        try:
            return_code = process.wait(timeout=wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                return_code = process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=5)
    path = root / "worker_records" / f"{run_id}.json"
    result = json.loads(path.read_bytes()) if path.is_file() and return_code == 0 else {
        "run_id": run_id, "status": "failed",
        "failure": {"type": "WorkerIncomplete", "message": "terminated or missing complete worker receipt"},
        "applied_steps": "unknown after last published checkpoint; never assumed zero",
        "last_guaranteed_checkpoint": "original frozen warmup state",
        "process_peak_rss_bytes": None}
    result["supervisor"] = {"return_code": return_code, "wall_timeout": timed_out,
        "elapsed_wall_ns": time.perf_counter_ns() - began,
        "reaped_child_cpu_ns": _child_cpu_ns() - child_cpu,
        "wall_cap_seconds": wall_seconds,
        "cpu_scope": "RUSAGE_CHILDREN difference; dedicated sequential owner has no other children",
        "logs": [f"worker_logs/{run_id}.stdout", f"worker_logs/{run_id}.stderr"]}
    return result


def execute(data, features, protocol, output, *, expected_protocol_sha256):
    sys.addaudithook(_deny_final_labels)
    began, cpu_began, children_before = time.perf_counter_ns(), time.process_time_ns(), _child_cpu_ns()
    data, features, protocol, root = map(Path, (data, features, protocol, output))
    plan = _plan(protocol, expected_protocol_sha256)
    if file_hash(data / "data_receipt.json") != plan["cohort_receipt_sha256"]:
        raise ValueError("new source cohort receipt differs from experiment freeze")
    _, _, receipt, labels, sources, matrix, feature_report = _inputs(data, features, protocol)
    if (receipt["cohort_protocol_sha256"] != plan["cohort_protocol_sha256"]
            or receipt["selected_registered_exposure_overlap"] != 0
            or receipt["selected_components"] != 480 or len(sources) != 480):
        raise ValueError("new prepared source-selection/exclusion identities differ")
    root.mkdir(parents=True, exist_ok=False)
    root = root.resolve()
    shutil.copyfile(protocol, root / "protocol.json")
    input_files = {"data_receipt": data / "data_receipt.json", "train_labels": data / "train_labels.json",
                   "sources": data / "sources.json", "feature_report": features / "report.json",
                   "features": features / "features.npz"}
    inputs = {name: {"path": str(path.resolve()), "sha256": file_hash(path)} for name, path in input_files.items()}
    _write(root / "input_manifest.json", {"protocol_sha256": expected_protocol_sha256, "inputs": inputs,
        "final_labels": {"sha256": receipt["files"]["final_labels.json"]["sha256"], "opened": False},
        "source_code_sha256": _code(), "authority": "DENY_ALL"})
    projected, projection = _project(matrix, plan)
    _arrays(root / "projected_features.npz", features=projected, projection=projection)
    projected_sha = file_hash(root / "projected_features.npz")
    feature_identity = {"shared_feature_identity": feature_report["feature_identity"],
        "encoder_identity": feature_report["encoder_identity"], "projection": plan["projection"],
        "projection_sha256": hashlib.sha256(projection.tobytes()).hexdigest(),
        "projected_tensor_sha256": hashlib.sha256(projected.tobytes()).hexdigest()}
    split = _split_arrays(projected, labels)
    contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
    predictions = np.full((18, len(projected), 4), np.nan)
    initial_predictions = np.full((6, len(projected), 4), np.nan)
    records, initials = [None] * 18, []
    for initial_index, (seed, mode) in enumerate((s, m) for s in plan["seeds"] for m in plan["head_modes"]):
        name = f"seed{seed}-{mode}"
        initial = {"initial_index": initial_index, "seed": seed, "head": mode, "status": "failed"}
        try:
            bindings = {"protocol_sha256": expected_protocol_sha256, "feature_identity": feature_identity,
                        "cohort_receipt_sha256": plan["cohort_receipt_sha256"], "seed": seed,
                        "head": mode, "source_code_sha256": _code(), "authority": "DENY_ALL"}
            state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=seed), bindings=bindings,
                                      protocol=plan["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
            wall, cpu, warm_steps = time.perf_counter_ns(), time.process_time_ns(), []
            for _ in range(plan["warmup_steps"]):
                warm_steps.append(state.advance(*split["old_train"]))
            initial["warmup"] = {"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}
            state.select_context("current_train")
            initial_path = f"initial/{name}"
            state.save(root / initial_path)
            _write(root / "warmup" / f"{name}.json", warm_steps)
            initial_predictions[initial_index] = state.head.predict_proba(projected)
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            reference = build_reference(state, *split["current_train"],
                probes=(split["current_probe"], split["old_probe"]), horizon=plan["horizon"], dt=plan["h"])
            initial["reference_build"] = {"wall_ns": time.perf_counter_ns() - wall,
                                            "cpu_ns": time.process_time_ns() - cpu,
                                            "derivative_audit": reference.derivative_audit}
            reference_path = f"references/{name}.npz"
            _arrays(root / reference_path, **reference.arrays(), train_features=reference.train_features,
                train_labels=reference.train_labels, probe_current_x=reference.probes[0][0],
                probe_current_y=reference.probes[0][1], probe_old_x=reference.probes[1][0], probe_old_y=reference.probes[1][1])
            initial.update(status="completed", original_state_sha256=state.digest(),
                anchor=float(reference.observations[0, 1]), initial_path=initial_path,
                parameter_count=state.parameter_count, private_parameters_bytes=state.parameter_vector().nbytes,
                full_numeric_state_bytes=state.vector().nbytes, reference_path=reference_path)
            start = initial_index % 3
            for arm in ARMS[start:] + ARMS[:start]:
                run_id, index = f"{name}-{arm}", initial_index * 3 + ARMS.index(arm)
                request = root / "worker_requests" / f"{run_id}.json"
                _write(request, {"run_root": str(root), "run_id": run_id, "arm": arm,
                    "initial_index": initial_index, "seed": seed, "head": mode,
                    "protocol_sha256": expected_protocol_sha256, "initial_path": initial_path,
                    "initial_state_sha256": state.digest(), "bindings": bindings, "contexts": contexts,
                    "reference_path": reference_path, "reference_sha256": file_hash(root / reference_path),
                    "projected_features_sha256": projected_sha, "feature_identity": feature_identity})
                record = supervise(request, root, run_id, plan["worker_wall_seconds"])
                record.update(arm=arm, initial_index=initial_index, seed=seed, head=mode)
                if record["status"] == "completed":
                    prediction_path = root / "conditions" / run_id / "predictions.npz"
                    if file_hash(prediction_path) != record["predictions_sha256"]:
                        raise ValueError("worker predictions changed before sealing")
                    with np.load(prediction_path, allow_pickle=False) as values:
                        predictions[index] = values["probabilities"]
                records[index] = record
                _write(root / "condition_records" / f"{run_id}.json", record)
                print(json.dumps({"run_id": run_id, "status": record["status"], "completed_records": sum(v is not None for v in records)}), flush=True)
        except Exception as error:
            initial.update(status="failed", failure={"type": type(error).__name__, "message": str(error)},
                           traceback=traceback.format_exc())
            for j, arm in enumerate(ARMS):
                index = initial_index * 3 + j
                if records[index] is None:
                    records[index] = {"run_id": f"{name}-{arm}", "arm": arm, "initial_index": initial_index,
                        "seed": seed, "head": mode, "status": "failed", "failure_stage": "initial_setup",
                        "failure": initial["failure"]}
        initials.append(initial)
    if any(record is None for record in records):
        raise ValueError("condition census incomplete")
    _arrays(root / "frozen_predictions.npz", final=predictions, initial=initial_predictions)
    result = {"schema": SCHEMA, "protocol_sha256": expected_protocol_sha256,
        "records": records, "initials": initials, "row_source_ids": [v["source_id"] for v in sources],
        "completed_conditions": sum(v["status"] == "completed" for v in records), "expected_conditions": 18,
        "controller_calls_are_cost_subsets": True,
        "shared_feature_cost": {key: feature_report[key] for key in ("encoder_load", "encoding", "tensor_bytes", "peak_rss_bytes")},
        "wall_ns": time.perf_counter_ns() - began, "owner_cpu_ns": time.process_time_ns() - cpu_began,
        "all_reaped_worker_cpu_ns": _child_cpu_ns() - children_before, "owner_process_peak_rss_bytes": _rss_bytes(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "final_labels_opened": False, "authority": "DENY_ALL"}
    if _code() != plan["source_code_sha256"] or any(file_hash(input_files[n]) != r["sha256"] for n, r in inputs.items()):
        raise ValueError("source or input identity changed during the condition census")
    _write(root / "summary.json", result)
    seal = {"schema": "hepta.cell-retention.prediction-seal.v1", "protocol_sha256": expected_protocol_sha256,
        "summary_sha256": file_hash(root / "summary.json"), "predictions_sha256": file_hash(root / "frozen_predictions.npz"),
        "input_manifest_sha256": file_hash(root / "input_manifest.json"), "sources_sha256": inputs["sources"]["sha256"],
        "final_labels_sha256": receipt["files"]["final_labels.json"]["sha256"],
        "expected_conditions": 18, "condition_failures_retained": True, "final_labels_opened": False}
    _write(root / "seal.json", seal)
    return {"completed_conditions": result["completed_conditions"], "expected_conditions": 18,
            "seal_sha256": file_hash(root / "seal.json"), "wall_ns": result["wall_ns"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    run = modes.add_parser("execute")
    for name in ("data", "features", "protocol", "output", "expected-protocol-sha256"):
        run.add_argument("--" + name, required=True)
    child = modes.add_parser("worker")
    child.add_argument("--request", required=True)
    child.add_argument("--expected-request-sha256", required=True)
    args = vars(parser.parse_args())
    mode = args.pop("mode")
    result = execute(**args) if mode == "execute" else worker(**args)
    if mode == "execute":
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
