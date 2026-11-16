"""Cold-process candidate recomputation and complete-state one-action replay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cell_field_action_control import plan_action
from cell_field_control import Reference
from cell_field_features import file_hash
from cell_field_state import CellTrainingState
from cell_learning_models import canonical, normalize_features


def deny_withheld_labels(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(arguments[0])
        if Path(name).name in ("final_labels.json", "validation_labels.json"):
            raise PermissionError("withheld label payload is forbidden during cold replay")


def _inside(root, relative):
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("replay paths must remain inside the declared run")
    result = root / value
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("replay input escaped the declared run")
    return result


def _arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name].copy() for name in archive.files}


def _arithmetic(value):
    if isinstance(value, dict):
        return {k: _arithmetic(v) for k, v in value.items() if k not in ("wall_ns", "cpu_ns")}
    if isinstance(value, list):
        return [_arithmetic(v) for v in value]
    return value


def _array_sha(value):
    value = np.ascontiguousarray(value)
    return hashlib.sha256(canonical([value.dtype.str, list(value.shape)]) + value.tobytes()).hexdigest()


def _write(path, value):
    path.write_bytes(canonical(value) + b"\n")


def child(job_path):
    sys.addaudithook(deny_withheld_labels)
    job = json.loads(Path(job_path).read_bytes())
    root, source = Path(job["root"]), Path(job["source_directory"])
    for name, expected in job["inputs"].items():
        if file_hash(_inside(root, name)) != expected:
            raise ValueError("cold replay input changed: " + name)
    for name, expected in job["source_hashes"].items():
        if file_hash(_inside(source, name)) != expected:
            raise ValueError("cold replay source changed: " + name)
    plan = json.loads((root / "inputs/protocol.json").read_bytes())
    if plan != job["protocol"]:
        raise ValueError("cold replay protocol binding differs")
    initial_manifest = json.loads((_inside(root, job["initial"]["checkpoint_path"]) / "manifest.json").read_bytes())
    state = CellTrainingState.load(_inside(root, job["start_checkpoint"]), initial_manifest["bindings"],
        expected_protocol=initial_manifest["protocol"], expected_contexts=initial_manifest["contexts"],
        expected_state_digest=job["start_state_sha256"])
    if state.step_count != initial_manifest["step_count"] + job["start"]:
        raise ValueError("cold replay step index differs from the complete common state")
    paths, start, horizon = job["record"]["paths"], job["start"], plan["evaluation_horizon"]
    inputs, ref_arrays = _arrays(root / "train_inputs.npz"), _arrays(_inside(root, paths["reference"]))
    probes = tuple((normalize_features(inputs[prefix + "_x"]), inputs[prefix + "_y"])
                   for prefix in ("current_probe", "old_probe"))
    reference = Reference(state, inputs["current_train_x"], inputs["current_train_y"], probes,
        ref_arrays["reference_states"], ref_arrays["reference_observations"],
        ref_arrays["state_scales"], ref_arrays["A"], ref_arrays["C_extended"], plan["h"], [], 0)
    saved = _arrays(_inside(root, paths["candidate"]))
    candidate_equal, predictions_equal = None, None
    if start == 0:
        model = _arrays(_inside(root, paths["model"]))
        proposed = plan_action(model, **job["record"]["planner_options"])
        if proposed["status"] != "qualified":
            raise ValueError("cold recomputation did not qualify the frozen candidate")
        values = {key: value for key, value in proposed.items() if isinstance(value, np.ndarray)}
        values.update({"problem__" + key: np.asarray(value) for key, value in proposed["problem"].items()})
        if any(name not in saved or not np.array_equal(value, saved[name]) for name, value in values.items()):
            raise ValueError("cold candidate arrays or certificate arithmetic differ")
        previous_record = json.loads(_inside(root, paths["candidate_record"]).read_bytes())
        candidate_equal = (previous_record["status"] == proposed["status"]
                           and _arithmetic(previous_record["record"]) == _arithmetic(proposed["record"]))
        if not candidate_equal:
            raise ValueError("cold candidate solver record differs excluding timing")
        predictions_equal = {}
        for observation, path in job["initial"]["model_paths"].items():
            model = _arrays(_inside(root, path))
            predicted = np.einsum("kij,j->ki", model["loss_maps"], proposed["u"])
            predictions_equal[observation] = np.array_equal(predicted, saved["predicted_" + observation + "_fields"])
        if not all(predictions_equal.values()):
            raise ValueError("same-action prediction changed in the cold process")
        actions = proposed["actions"]
    else:
        actions = saved["actions"].copy()
    expected = _arrays(_inside(root, paths["trajectory"]))
    p = state.parameter_count
    if (actions.shape != (horizon, p) or not np.isfinite(actions).all()
            or np.any(actions[1:] != 0) or not np.array_equal(actions, expected["actions"])
            or np.any(np.abs(actions) > plan["action_bound"] / np.sqrt(p))):
        raise ValueError("replay action differs from the bounded common one-intervention sequence")
    states, observations, receipts = [], [], []
    for k in range(start, horizon + 1):
        states.append(state.vector())
        observations.append(reference.observe(state.vector())[0])
        if k < horizon:
            receipts.append(state.advance(reference.train_features, reference.train_labels,
                intervention=reference.dt * actions[k], mask=np.ones(p, dtype=bool)))
    observations = np.asarray(observations)
    replayed = {"states": np.asarray(states), "observations": observations,
                "actions": actions[start:].copy(),
                "fields": observations[:, :2] - reference.observations[start:, :2]}
    matches = {key: np.array_equal(value, expected[key][start:]) for key, value in replayed.items()}
    expected_receipts = json.loads(_inside(root, paths["receipts"]).read_bytes())
    matches["transition_receipts"] = receipts == expected_receipts[start:]
    matches["final_state_digest"] = state.digest() == job["record"]["final_state_sha256"]
    prefix = _inside(root, job["output_prefix"])
    final_path = Path(str(prefix) + ".checkpoint")
    state.save(final_path)
    actual_manifest = json.loads((final_path / "manifest.json").read_bytes())
    original_manifest = json.loads((_inside(root, paths["checkpoint"]) / "manifest.json").read_bytes())
    matches["complete_final_manifest"] = actual_manifest == original_manifest
    np.savez_compressed(str(prefix) + ".npz", **replayed)
    result = {"schema": "hepta.cell-action-cold-replay-result.v3", "run_id": job["record"]["run_id"],
        "segment": job["segment"], "start": start, "start_step": initial_manifest["step_count"] + start,
        "final_step": state.step_count, "state_sha256": state.digest(), "matches": matches,
        "candidate_recomputed": start == 0, "candidate_arithmetic_equal_excluding_timing": candidate_equal,
        "both_model_predictions_equal": predictions_equal, "receipts": receipts,
        "arrays": {key: {"sha256": _array_sha(value), "shape": list(value.shape), "dtype": value.dtype.str}
                   for key, value in replayed.items()},
        "validation_labels_opened": False, "final_labels_opened": False, "authority": "DENY_ALL"}
    _write(Path(str(prefix) + ".json"), result)
    if not all(matches.values()):
        raise ValueError("complete-state replay mismatch: " + str(matches))
    return {key: result[key] for key in ("run_id", "segment", "start_step", "final_step", "matches")}


def verify_action_replays(root, record, initial, plan, source_hashes, source_directory):
    """Whole first-action recomputation and midpoint zero-continuation in fresh processes."""
    root, source = Path(root).resolve(), Path(source_directory).resolve()
    required = {"cell_field_action_replay.py", "cell_field_action_control.py", "cell_field_state.py"}
    if (not required.issubset(source_hashes) or record["status"] != "completed"
            or "midpoint" not in record["paths"] or record["method_id"] == "zero"):
        raise ValueError("completed registered replay target and frozen source closure required")
    if json.loads((root / "inputs/protocol.json").read_bytes()) != plan:
        raise ValueError("replay protocol is not the stored protocol")
    (root / "replay").mkdir(exist_ok=True)
    paths, results = record["paths"], []
    receipts = json.loads(_inside(root, paths["receipts"]).read_bytes())
    base_inputs = {"inputs/protocol.json", "train_inputs.npz", "projected_features.npz",
                   paths["reference"], paths["model"], paths["candidate"], paths["candidate_record"],
                   paths["trajectory"], paths["receipts"], *initial["model_paths"].values()}
    for directory in (initial["checkpoint_path"], paths["midpoint"], paths["checkpoint"]):
        base_inputs.update({directory + "/manifest.json", directory + "/state.npz"})
    identities = {name: file_hash(_inside(root, name)) for name in sorted(base_inputs)}
    for start, segment in ((0, "whole"), (plan["evaluation_horizon"] // 2, "midpoint")):
        prefix = f"replay/{record['run_id']}-{segment}"
        job_path = _inside(root, prefix + ".job.json")
        if job_path.exists():
            raise ValueError("cold replay output already exists")
        start_checkpoint = initial["checkpoint_path"] if start == 0 else paths["midpoint"]
        start_digest = initial["state_sha256"] if start == 0 else receipts[start - 1]["state_sha256"]
        job = {"schema": "hepta.cell-action-cold-replay-job.v3", "root": str(root),
            "source_directory": str(source), "source_hashes": source_hashes, "inputs": identities,
            "record": record, "initial": initial, "protocol": plan, "start": start,
            "segment": segment, "start_checkpoint": start_checkpoint,
            "start_state_sha256": start_digest, "output_prefix": prefix}
        _write(job_path, job)
        command = [sys.executable, "-B", str(source / "cell_field_action_replay.py"), "--job", str(job_path)]
        began = time.perf_counter_ns()
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as error:
            for label, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                value = value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                _inside(root, prefix + "." + label + ".log").write_text(value)
            _write(_inside(root, prefix + ".process.json"), {"command": command, "timeout_seconds": 60,
                    "status": "timeout", "wall_ns": time.perf_counter_ns() - began})
            raise ValueError("cold replay process exceeded 60 seconds") from error
        wall = time.perf_counter_ns() - began
        _inside(root, prefix + ".stdout.log").write_text(process.stdout)
        _inside(root, prefix + ".stderr.log").write_text(process.stderr)
        _write(_inside(root, prefix + ".process.json"), {"command": command, "exit_code": process.returncode,
                "wall_ns": wall, "child_cpu_measured": False})
        if process.returncode != 0:
            raise ValueError("cold replay child failed: " + segment + "; exit " + str(process.returncode))
        result = json.loads(_inside(root, prefix + ".json").read_bytes())
        if not all(result["matches"].values()):
            raise ValueError("cold replay child did not verify all exact comparisons")
        results.append({"run_id": record["run_id"], "segment": segment, "status": "completed",
            "start_step": result["start_step"], "final_step": result["final_step"],
            "matches": result["matches"], "candidate_recomputed": result["candidate_recomputed"],
            "candidate_arithmetic_equal_excluding_timing": result["candidate_arithmetic_equal_excluding_timing"],
            "wall_ns_including_process": wall, "result_path": prefix + ".json",
            "arrays_path": prefix + ".npz", "job_path": prefix + ".job.json"})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    print(json.dumps(child(parser.parse_args().job)))
