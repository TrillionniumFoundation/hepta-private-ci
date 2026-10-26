"""Compact development evidence; preserve raw cost records without probability paths."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_field_action_io import _json_value, save_arrays, write_json
from cell_field_controller_v7 import load_snapshot, make_contract
from cell_field_development_audit_v7 import audit_policy, audit_stopped_controller, per_source_nll, replay_actions
from cell_learning_models import canonical


CHECKPOINT_STEPS = (0, 16, 17, 32)


def write_compressed(path, value):
    content = canonical(_json_value(value))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
            compressed.write(content)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
        "canonical_uncompressed_sha256": hashlib.sha256(content).hexdigest(), "uncompressed_bytes": len(content)}


def read_compressed(path, limit=16 << 20):
    with gzip.open(path, "rb") as stream:
        content = stream.read(limit+1)
    if len(content) > limit:
        raise ValueError("development record exceeds its expanded bound")
    return json.loads(content)


def save_result(directory, identity, warmup, inputs, anchors, policy, configuration,
                result, call_cost, warm_old_losses, *, controller_identity=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    record = result["record"]
    compressed = write_compressed(directory/"policy-record.json.gz", record)
    try:
        audit = audit_policy(warmup, inputs["split"]["current_train"], inputs["current_panels"],
            inputs["old_panels"], anchors, policy, configuration, result, controller_identity=controller_identity)
    except Exception as error:
        audit = {"passed": False, "error": {"type": type(error).__name__, "message": str(error)}}
    scoring_cpu, scoring_wall = time.process_time_ns(), time.perf_counter_ns()
    evaluation_error, future, old_delta = None, np.empty(0), np.empty(0)
    try:
        future = per_source_nll(result["state"], inputs["selection"]["future"])
        old_delta = per_source_nll(result["state"], inputs["selection"]["old"])-warm_old_losses
    except Exception as error:
        evaluation_error = {"type": type(error).__name__, "message": str(error)}
    scoring = {"cpu_ns": time.process_time_ns()-scoring_cpu, "wall_ns": time.perf_counter_ns()-scoring_wall}
    save_arrays(directory/"compact.npz", {"actions": result["actions"], "terminal_vector": result["state"].vector(),
        "future_losses": future, "old_differences": old_delta})
    trace = {"receipts": result["receipts"],
        "state_sha256": [state.digest() for state in result["states"]],
        "controller_sha256": [hashlib.sha256(canonical(c)).hexdigest() for c in result["controllers"]]}
    trace_file = write_compressed(directory/"trace.json.gz", trace)
    checkpoints = {str(step): result["controllers"][step] for step in CHECKPOINT_STEPS if step < len(result["controllers"])}
    controller_file = write_compressed(directory/"controller-checkpoints.json.gz", checkpoints)
    errors = [value for value in (record.get("error"), audit.get("error"), audit.get("actual_errors"), evaluation_error) if value]
    row = {**identity, "policy": policy, "status": record["status"], "completed_steps": record["completed_steps"],
        "error": errors or None, "audit_passed": audit["passed"],
        "cpu_ns": call_cost["cpu_ns"], "wall_ns": call_cost["wall_ns"], "policy_core_cpu_ns": record["cpu_ns"],
        "cost_scope": "entire execute_policy call; data loading, shared original anchors, independent audit/scoring and disk separate",
        "future_mean_nll": float(future.mean()) if future.shape == (512,) else None,
        "old_mean_difference": float(old_delta.mean()) if old_delta.shape == (512,) else None,
        "terminal_state_sha256": result["state"].digest(), "policy_record": compressed,
        "trace_file": trace_file, "controller_file": controller_file, "audit": audit, "scoring": scoring,
        "scientific_acceptance": False}
    if call_cost["cpu_ns"] < record["cpu_ns"]:
        row.update(error={"type": "CostAccountingError", "message": "entire call time is below its recorded core time"}, audit_passed=False)
    write_json(directory/"result.json", row)
    return {**row, "future_losses": future, "old_differences": old_delta}


def save_failure(directory, identity, policy, error, call_cost):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    row = {**identity, "policy": policy, "status": "unavailable_execution_error", "completed_steps": None,
        "error": {"type": type(error).__name__, "message": str(error)}, "audit_passed": False,
        **call_cost, "future_mean_nll": None, "old_mean_difference": None, "scientific_acceptance": False}
    write_json(directory/"result.json", row)
    return {**row, "future_losses": np.empty(0), "old_differences": np.empty(0)}


def materialize_checkpoints(directory, warmup, inputs, anchors, policy, configuration, *, controller_identity=None):
    """Write full states only for the chosen configuration, using original bytes."""
    directory = Path(directory)
    trace = read_compressed(directory/"trace.json.gz")
    controllers = read_compressed(directory/"controller-checkpoints.json.gz")
    with np.load(directory/"compact.npz", allow_pickle=False) as values:
        actions = values["actions"]
    states = replay_actions(warmup, inputs["split"]["current_train"], actions, configuration["dt"],
        trace["receipts"], trace["state_sha256"])
    expected = make_contract(warmup, inputs["split"]["current_train"], inputs["current_panels"],
        inputs["old_panels"], anchors, policy, configuration, **(controller_identity or {}))
    saved = []
    for step in CHECKPOINT_STEPS:
        if step >= len(states):
            continue
        content = canonical(controllers[str(step)])
        if hashlib.sha256(content).hexdigest() != trace["controller_sha256"][step]:
            raise ValueError("selected controller canonical bytes changed")
        if controllers[str(step)].get("run_status") == "stopped":
            audit_stopped_controller(controllers[str(step)], states, trace["receipts"], expected,
                read_compressed(directory/"policy-record.json.gz"))
        else:
            load_snapshot(content, states[step], expected, expected_sha256=trace["controller_sha256"][step])
        target = directory/"selected-checkpoints"/str(step)
        states[step].save(target/"state")
        (target/"controller.json").write_bytes(content)
        saved.append({"step": step, "state_sha256": states[step].digest(), "controller_sha256": trace["controller_sha256"][step]})
    write_json(directory/"selected-checkpoints.json", {"checkpoints": saved,
        "scope": "exact original controller bytes and complete replayed Adam state; no replanning"})
    return actions, states
