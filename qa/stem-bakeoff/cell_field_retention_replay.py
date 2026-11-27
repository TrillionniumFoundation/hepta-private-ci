"""Cold-process continuation of the pure, zero-start retention MPC policy."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cell_field_control import Reference
from cell_field_features import file_hash
from cell_field_retention_control import RetentionController
from cell_field_run import _deny_final_labels
from cell_field_state import CellTrainingState
from cell_learning_models import canonical


def policy_options(controller):
    return {key: getattr(controller, key) for key in
            ("mode", "mask", "dt", "effort_price", "retention_tolerance",
             "max_iterations", "gap_tolerance")}


def feedback_segment(state, reference, controller, start, stop):
    """Recompute each optimal plan; a stored action tape is never an input."""
    states, observations, actions, receipts = [], [], [], []
    mask = np.any(controller.B != 0, axis=1)
    for k in range(start, stop + 1):
        vector = state.vector()
        measured, _ = reference.observe(vector)
        states.append(vector)
        observations.append(measured)
        if k == stop:
            break
        observation = ((vector - reference.states[k]) / reference.scales
                       if controller.mode == "full" else
                       measured[:controller.Cobs.shape[1]]
                       - reference.observations[k, :controller.Cobs.shape[1]])
        action = controller.action(k, observation)
        actions.append(action)
        receipts.append(state.advance(reference.train_features, reference.train_labels,
            intervention=reference.dt * controller.B @ action, mask=mask))
    return {"states": np.asarray(states), "observations": np.asarray(observations),
            "actions": np.asarray(actions)}, receipts


def child(job_path):
    sys.addaudithook(_deny_final_labels)
    job_path = Path(job_path)
    job, root = json.loads(job_path.read_bytes()), job_path.parent
    for name, expected in job["inputs"].items():
        if file_hash(root / name) != expected:
            raise ValueError("cold replay input changed")
    for name, expected in job["source_hashes"].items():
        if file_hash(Path(__file__).with_name(name)) != expected:
            raise ValueError("cold replay source differs from frozen code")
    state = CellTrainingState.load(root / "input-state", job["bindings"],
        expected_protocol=job["protocol"], expected_contexts=job["contexts"],
        expected_state_digest=job["state_sha256"])
    with np.load(root / "replay-inputs.npz", allow_pickle=False) as archive:
        values = {key: archive[key].copy() for key in archive.files}
    probes = tuple((values[prefix + "_x"], values[prefix + "_y"])
                   for prefix in ("current_probe", "old_probe"))
    reference = Reference(state, values["train_x"], values["train_y"], probes,
        values["reference_states"], values["reference_observations"], values["state_scales"],
        np.empty((job["horizon"], 0, 0)), np.empty((0, 0, 0)), job["policy"]["dt"], [], 0)
    controller = RetentionController.from_arrays(values, **job["policy"])
    arrays, receipts = feedback_segment(state, reference, controller, job["start"], job["horizon"])
    np.savez_compressed(root / "replayed.npz", **arrays)
    state.save(root / "restored-final")
    result = {"state_sha256": state.digest(), "step_count": state.step_count,
              "receipts": receipts, "solver_records": controller.records,
              "action_source": "fresh zero-start feedback optimization",
              "authority": "DENY_ALL"}
    (root / "result.json").write_bytes(canonical(result) + b"\n")
    return {key: result[key] for key in ("state_sha256", "step_count", "action_source")}


def verify_retention_replay(output, state, reference, controller, rollout, source_hashes):
    """Save and restart both a whole feedback path and a midpoint continuation."""
    output = Path(output)
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    results, options = [], policy_options(controller)
    for start in (0, reference.horizon // 2):
        directory = output / ("whole" if start == 0 else "midpoint")
        directory.mkdir(parents=True, exist_ok=False)
        initial = state.clone()
        if start:
            policy = RetentionController.from_arrays(controller.arrays(), **options)
            prefix, _ = feedback_segment(initial, reference, policy, 0, start)
            if not np.array_equal(prefix["states"], rollout["states"][:start + 1]):
                raise ValueError("recomputed prefix differs before checkpoint")
        initial.save(directory / "input-state")
        np.savez_compressed(directory / "replay-inputs.npz",
            train_x=reference.train_features, train_y=reference.train_labels,
            current_probe_x=reference.probes[0][0], current_probe_y=reference.probes[0][1],
            old_probe_x=reference.probes[1][0], old_probe_y=reference.probes[1][1],
            reference_states=reference.states, reference_observations=reference.observations,
            state_scales=reference.scales, **controller.arrays())
        job = {"schema": "hepta.cell-retention-cold-replay.v2", "bindings": initial.bindings,
               "protocol": initial.protocol, "contexts": initial.contexts,
               "state_sha256": initial.digest(), "start": start, "horizon": reference.horizon,
               "policy": options, "source_hashes": source_hashes,
               "inputs": {name: file_hash(directory / name) for name in
                          ("input-state/manifest.json", "input-state/state.npz", "replay-inputs.npz")}}
        (directory / "job.json").write_bytes(canonical(job) + b"\n")
        wall = time.perf_counter_ns()
        process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                  "--job", str((directory / "job.json").resolve())],
                                 capture_output=True, text=True, timeout=180)
        elapsed = time.perf_counter_ns() - wall
        (directory / "stdout.txt").write_text(process.stdout)
        (directory / "stderr.txt").write_text(process.stderr)
        if process.returncode != 0:
            raise ValueError(f"cold replay child failed: exit {process.returncode}")
        with np.load(directory / "replayed.npz", allow_pickle=False) as replayed:
            matches = {key: np.array_equal(replayed[key], rollout[key][start:])
                       for key in ("states", "observations", "actions")}
        result = json.loads((directory / "result.json").read_bytes())
        matches["transition_receipts"] = result["receipts"] == rollout["receipts"][start:]
        final = CellTrainingState.load(directory / "restored-final", initial.bindings,
            expected_protocol=initial.protocol, expected_contexts=initial.contexts,
            expected_state_digest=rollout["state"].digest())
        matches["complete_final_state"] = final.digest() == rollout["state"].digest()
        if not all(matches.values()):
            raise ValueError(f"cold feedback replay differs: {matches}")
        results.append({"start_step": start, "wall_ns_including_process": elapsed,
                        "matches": matches, "state_sha256": final.digest()})
    report = {"schema": "hepta.cell-retention-recovery.v2", "policy": controller.mode,
              "mask": controller.mask, "checks": results, "all_exact": True,
              "wall_ns": time.perf_counter_ns() - began,
              "parent_cpu_ns": time.process_time_ns() - cpu_began,
              "child_cpu_measured": False, "authority": "DENY_ALL"}
    (output / "report.json").write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    print(json.dumps(child(parser.parse_args().job)))
