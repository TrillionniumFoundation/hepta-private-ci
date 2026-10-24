"""Cold-process replay of a frozen Cell feedback policy from complete state."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cell_field_control import Reference
from cell_field_state import CellTrainingState
from cell_learning_models import canonical


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def feedback_segment(state, reference, arrays, mode, start, stop):
    """Recompute each feedback action; never consume an observed-action tape."""
    states, observations, actions, receipts = [], [], [], []
    mask = np.any(arrays["B"] != 0, axis=1)
    for k in range(start, stop + 1):
        vector = state.vector()
        measured, _ = reference.observe(vector)
        states.append(vector)
        observations.append(measured)
        if k == stop:
            break
        if mode == "full":
            observation = (vector - reference.states[k]) / reference.scales
        else:
            q = arrays["K"].shape[2]
            observation = measured[:q] - reference.observations[k, :q]
        action = -arrays["K"][k] @ observation + arrays["offset"][k]
        actions.append(action)
        receipts.append(state.advance(reference.train_features, reference.train_labels,
            intervention=reference.dt * arrays["B"] @ action, mask=mask))
    return {"states": np.asarray(states), "observations": np.asarray(observations),
            "actions": np.asarray(actions)}, receipts


def child(job_path):
    job_path = Path(job_path)
    job, root = json.loads(job_path.read_bytes()), job_path.parent
    for name, expected in job["inputs"].items():
        if file_hash(root / name) != expected:
            raise ValueError("cold replay input identity changed")
    state = CellTrainingState.load(root / "input-state", job["bindings"],
        expected_protocol=job["protocol"], expected_contexts=job["contexts"],
        expected_state_digest=job["state_sha256"])
    with np.load(root / "replay-inputs.npz", allow_pickle=False) as source:
        values = {key: source[key].copy() for key in source.files}
    # Reference.probes were already normalized once in build_reference.
    probes = tuple((values[prefix + "_x"], values[prefix + "_y"])
                   for prefix in ("current_probe", "old_probe"))
    reference = Reference(state, values["train_x"], values["train_y"], probes,
        values["reference_states"], values["reference_observations"], values["state_scales"],
        np.empty((job["horizon"], 0, 0)), np.empty((0, 0, 0)), job["dt"], [], 0)
    arrays, receipts = feedback_segment(state, reference, values, job["mode"], job["start"], job["horizon"])
    np.savez_compressed(root / "replayed.npz", **arrays)
    state.save(root / "restored-final")
    result = {"state_sha256": state.digest(), "step_count": state.step_count,
              "receipts": receipts, "action_source": "recomputed feedback",
              "authority": "DENY_ALL"}
    (root / "result.json").write_bytes(canonical(result) + b"\n")
    return {key: result[key] for key in ("state_sha256", "step_count", "action_source")}


def verify_replay(output, state, reference, controller, rollout):
    """Check full-path and midpoint resumes in separate interpreter processes."""
    output = Path(output)
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    results = []
    policy = controller.arrays()
    for start in (0, reference.horizon // 2):
        directory = output / ("whole" if start == 0 else "midpoint")
        directory.mkdir(parents=True, exist_ok=False)
        initial = state.clone()
        if start:
            prefix, _ = feedback_segment(initial, reference, policy, controller.mode, 0, start)
            if not np.array_equal(prefix["states"], rollout["states"][:start + 1]):
                raise ValueError("feedback reconstruction differs before saved checkpoint")
        initial.save(directory / "input-state")
        np.savez_compressed(directory / "replay-inputs.npz",
            train_x=reference.train_features, train_y=reference.train_labels,
            current_probe_x=reference.probes[0][0], current_probe_y=reference.probes[0][1],
            old_probe_x=reference.probes[1][0], old_probe_y=reference.probes[1][1],
            reference_states=reference.states, reference_observations=reference.observations,
            state_scales=reference.scales, B=controller.B, K=controller.K, offset=controller.offset)
        job = {"schema": "hepta.cell-field-cold-replay.v1", "bindings": initial.bindings,
               "protocol": initial.protocol, "contexts": initial.contexts,
               "state_sha256": initial.digest(), "start": start, "horizon": reference.horizon,
               "mode": controller.mode, "dt": reference.dt,
               "inputs": {name: file_hash(directory / name) for name in
                          ("input-state/manifest.json", "input-state/state.npz", "replay-inputs.npz")}}
        (directory / "job.json").write_bytes(canonical(job) + b"\n")
        wall = time.perf_counter_ns()
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                  "--job", str((directory / "job.json").resolve())],
                                 capture_output=True, text=True, timeout=120)
        elapsed = time.perf_counter_ns() - wall
        (directory / "stdout.txt").write_text(process.stdout)
        (directory / "stderr.txt").write_text(process.stderr)
        if process.returncode != 0:
            raise ValueError(f"cold replay child failed: exit {process.returncode}")
        with np.load(directory / "replayed.npz", allow_pickle=False) as replayed:
            matches = {key: np.array_equal(replayed[key], rollout[key][start:])
                       for key in ("states", "observations", "actions")}
        final = CellTrainingState.load(directory / "restored-final", initial.bindings,
            expected_protocol=initial.protocol, expected_contexts=initial.contexts,
            expected_state_digest=rollout["state"].digest())
        matches["complete_final_state"] = final.digest() == rollout["state"].digest()
        if not all(matches.values()):
            raise ValueError(f"cold replay differs from uninterrupted path: {matches}")
        results.append({"start_step": start, "wall_ns_including_process": elapsed,
                        "matches": matches, "state_sha256": final.digest()})
    report = {"schema": "hepta.cell-field-recovery.v1", "policy": controller.mode,
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
