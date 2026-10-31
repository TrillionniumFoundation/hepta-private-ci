"""Minimal independent deployment review of the separately frozen joint fits.

Checks all saved inactive parameters, then the predeclared first eight heldout
worlds of seed 11 for each family and each stage (64 recorded trajectories).
It does not fit, inspect gradients, select models, or launch additional worlds.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from ...round7.task import ACTIONS, TaskParameters, features, generate_episode, initial_state, step
from ..kernels import BrownianEventDynamics
from .full_joint import MODES, SEEDS, load_joint, settings, sha, verify_registration
from .independent_confirmation_audit import verify_frozen


def uniform(seed, call, channel):
    payload = f"round7/policy/v1/{seed}/{call}/{channel}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / 2**64


def choose(probabilities, value):
    cumulative = np.cumsum(probabilities)
    return min(len(probabilities) - 1, int(np.searchsorted(cumulative, value, side="right")))


@torch.no_grad()
def run(root, remote_candidate_commit):
    root = Path(root)
    output = root / "evidence/full_joint_v1"
    destination = output / "INDEPENDENT_DEPLOYMENT_REVIEW.json"
    if destination.exists():
        raise FileExistsError(destination)
    if len(remote_candidate_commit) != 40 or any(c not in "0123456789abcdef" for c in remote_candidate_commit):
        raise ValueError("the coordinator's published candidate commit is required")
    torch.set_num_threads(1)
    base_freeze = verify_frozen(root)
    registration_path, candidate_path = output / "REGISTRATION.json", output / "CANDIDATES.json"
    verify_registration(registration_path)
    candidates = json.loads(candidate_path.read_text())
    candidate_sha = sha(candidate_path)
    if candidates["registration_sha256"] != sha(registration_path):
        raise AssertionError("registration/candidate identity mismatch")
    index = {(row["mode"], row["seed"]): row for row in candidates["cases"]}
    if set(index) != {(mode, seed) for mode in MODES for seed in SEEDS}:
        raise AssertionError("candidate matrix incomplete")
    constraints, selected = [], {}
    for mode in MODES:
        for seed in SEEDS:
            folder = output / "cases" / f"{mode}_{seed}"
            registered = index[mode, seed]
            if sha(folder / "TRAINING.json") != registered["training_sha256"]:
                raise AssertionError("training artifact changed")
            records, models = {}, {}
            for stage in ("initial", "final"):
                path = folder / f"{stage}.json"
                if sha(path) != registered[f"{stage}_sha256"]:
                    raise AssertionError("candidate bytes changed")
                records[stage] = json.loads(path.read_text())
                model, metadata = load_joint(path)
                models[stage] = model
                for name, tensor in model.state_dict().items():
                    if not torch.equal(tensor, torch.as_tensor(records[stage]["state_dict"][name], dtype=tensor.dtype)):
                        raise AssertionError("checkpoint load changed a parameter")
                actual_frozen = {name for name, parameter in model.named_parameters() if not parameter.requires_grad}
                expected_frozen = {"core.raw_leak"}
                if mode == "direct":
                    expected_frozen = {name for name, _ in model.named_parameters() if name.startswith(("core.", "drive."))}
                elif mode == "continuous":
                    expected_frozen.update(("core.raw_reset_plus", "core.raw_reset_minus", "core.raw_recovery"))
                if actual_frozen != expected_frozen or set(metadata["frozen_parameters"]) != expected_frozen:
                    raise AssertionError("inactive parameter constraint does not survive loading")
                if mode != "direct":
                    if not isinstance(model.core, BrownianEventDynamics) or float(model.core.physical_parameters()["leak"]) != 0.0:
                        raise AssertionError("new model loaded as an old OU/CTMC kernel")
                if model.n_grid != 15 or metadata["head"] != 1 or metadata["temperature"] != 0.12:
                    raise AssertionError("checkpoint policy configuration mismatch")
            initial, final = models["initial"].state_dict(), models["final"].state_dict()
            for name in expected_frozen:
                if not torch.equal(initial[name], final[name]):
                    raise AssertionError("a declared inactive parameter changed during learning")
            for name in ("readout.2.weight", "readout.2.bias"):
                if not torch.equal(initial[name][:len(ACTIONS)], final[name][:len(ACTIONS)]):
                    raise AssertionError("unused head-zero output weights changed")
            constraints.append({"mode": mode, "fit_seed": seed, "inactive_parameters": sorted(expected_frozen),
                                "inactive_weights_unchanged": True, "head_zero_output_rows_unchanged": True,
                                "saved_parameter_roundtrip_exact": True})
            if seed == 11:
                selected[mode] = models
    protocol = settings()
    parameters = [TaskParameters(**row) for row in protocol["heldout_configurations"]]
    source_world_start = protocol["rollout"]["world_seed_start"]["heldout"]
    source_latent_start = protocol["rollout"]["latent_seed_start"]["heldout"]
    temperature = protocol["training"]["temperature"]
    max_q_error = max_event_error = max_row_defect = max_utility_error = 0.0
    minimum_boundary_distance = 1.0
    checked, state_transitions, transition_types, stop_events = [], 0, Counter(), 0
    for mode in MODES:
        folder = output / "cases" / f"{mode}_11"
        completed = json.loads((folder / "EVALUATION.json").read_text())
        if (completed["mode"], completed["fit_seed"]) != (mode, 11):
            raise AssertionError("recorded evaluation identity mismatch")
        with gzip.open(folder / "paired_rollouts.jsonl.gz", "rt", encoding="utf8") as stream:
            rows = [json.loads(line) for line in stream]
        chosen_rows = [row for row in rows if row["regime"] == "heldout" and
                       0 <= row["world_seed"] - source_world_start < 8]
        if len(chosen_rows) != 8:
            raise AssertionError("the declared heldout replay subset is incomplete")
        cache = {}
        for row in chosen_rows:
            episode_index = row["world_seed"] - source_world_start
            if row["configuration_index"] != episode_index % 4 or row["latent_seed"] != source_latent_start + episode_index:
                raise AssertionError("wrong public configuration or paired latent seed")
            episode = generate_episode(row["world_seed"], parameters[episode_index % 4])
            for stage in ("initial", "final"):
                model, recorded = selected[mode][stage], row["runs"][stage]
                state, previous, rewards, event_count = initial_state(episode), model.n_grid // 2, [], 0
                for call, trace in enumerate(recorded["steps"]):
                    if trace["before"] != state.to_dict():
                        raise AssertionError("public observation prefix mismatch")
                    key = stage, state
                    if key not in cache:
                        x = torch.from_numpy(features(state)[None])
                        content, drive = model.encode(x)
                        if mode == "direct":
                            matrix = np.eye(model.core.n_states, dtype=np.float64)
                        else:
                            matrix = model.core.transition_matrix(drive)[0][0].numpy()
                        q = model.state_action_values(x, content)[0, :, 1, :].numpy()
                        cache[key] = matrix, q
                    matrix, scores = cache[key]
                    probabilities = np.clip(matrix[previous], 0, None)
                    max_row_defect = max(max_row_defect, abs(float(probabilities.sum()) - 1.0))
                    probabilities /= probabilities.sum()
                    draw = uniform(row["latent_seed"], call, "latent")
                    latent = choose(probabilities, draw)
                    minimum_boundary_distance = min(minimum_boundary_distance, float(np.abs(np.cumsum(probabilities) - draw).min()))
                    prediction = trace["prediction"]
                    if not np.array_equal(np.asarray(prediction["mass"]), np.eye(1, len(probabilities), latent)[0]):
                        raise AssertionError("deployed latent successor does not follow the normalized law")
                    error = float(np.abs(scores[latent] - prediction["q"]).max())
                    max_q_error = max(max_q_error, error)
                    if error > 1e-12:
                        raise AssertionError("deployed policy scores differ after loading")
                    allowed = trace["result"]["info"]["legal_actions"]
                    logits = np.array([scores[latent, i] / temperature if action in allowed else -np.inf
                                       for i, action in enumerate(ACTIONS)])
                    action_probabilities = np.exp(logits - logits.max())
                    action_probabilities /= action_probabilities.sum()
                    draw = uniform(row["latent_seed"], call, "action")
                    action = ACTIONS[choose(action_probabilities, draw)]
                    minimum_boundary_distance = min(minimum_boundary_distance, float(np.abs(np.cumsum(action_probabilities) - draw).min()))
                    if action != trace["requested_action"]:
                        raise AssertionError("action was not drawn from the declared temperature-0.12 soft policy")
                    emitted = int(previous < model.n_grid and latent >= model.n_grid)
                    if emitted != prediction["event_count"]:
                        raise AssertionError("sampled event charge mismatch")
                    expected_event = float(probabilities[model.n_grid:].sum()) if previous < model.n_grid else 0.0
                    max_event_error = max(max_event_error, abs(expected_event - prediction["expected_event_count"]))
                    result = step(state, action, episode)
                    if result.to_dict() != trace["result"]:
                        raise AssertionError("external successor or task fee mismatch")
                    rewards.append(result.reward)
                    event_count += emitted
                    transition_types[f"{mode}:{'active' if previous < model.n_grid else 'refractory'}_to_{'active' if latent < model.n_grid else 'refractory'}"] += 1
                    stop_events += int(action == "STOP" and emitted)
                    previous, state = latent, result.state
                    state_transitions += 1
                if not state.terminated or state.to_dict() != recorded["final_state"]:
                    raise AssertionError("termination state mismatch")
                utility = math.fsum(rewards) - 0.0005 * len(rewards) - 0.0002 * event_count
                error = abs(utility - recorded["registered_return"])
                max_utility_error = max(max_utility_error, error)
                if error > 1e-12 or event_count != recorded["event_count"]:
                    raise AssertionError("full episode utility mismatch")
                checked.append({"mode": mode, "stage": stage, "world_seed": row["world_seed"],
                                "configuration_index": row["configuration_index"], "decisions": len(rewards),
                                "events": event_count, "utility_replay_error": error})
    if len(checked) != 64 or max_row_defect > 2e-10 or max_event_error > 2e-10:
        raise AssertionError("declared subset or probability tolerances failed")
    verify_registration(registration_path)
    if sha(candidate_path) != candidate_sha or verify_frozen(root) != base_freeze:
        raise AssertionError("candidate identity or original freeze changed during review")
    report = {"schema": "hepta.full-joint-independent-deployment-review.v1", "passed": True,
              "remote_candidate_commit": remote_candidate_commit, "candidate_freeze_sha256": candidate_sha,
              "registration_sha256": sha(registration_path), "original_round8_freeze_sha256": base_freeze,
              "selection": "Predeclared read-only replay: seed11, every family and initial/final stage, first8 new-heldout worlds; no performance selection",
              "all_fit_parameter_constraints": constraints, "trajectories_replayed": len(checked),
              "internal_and_action_sampling_steps": state_transitions, "transition_types_observed": dict(transition_types),
              "sampled_event_during_STOP_count": stop_events, "maximum_score_error": max_q_error,
              "maximum_expected_event_roundoff_difference": max_event_error,
              "maximum_pre_normalization_row_defect": max_row_defect,
              "minimum_random_draw_to_CDF_boundary_distance": minimum_boundary_distance,
              "maximum_utility_replay_error": max_utility_error, "records": checked,
              "objective_assessment": "Normalized latent transition then temperature0.12 soft action, full public successors and future resets/recovery; current compute/event fees are incurred once, including STOP. Pure-return scores are not asserted calibrated Q values.",
              "limits": "No new gradient computation, extra world generation beyond reconstructing recorded worlds, model selection or native qualification. Head0 output weights are unchanged, but shared hidden readout changes can change head0 predictions.",
              "source_sha256": sha(__file__)}
    with destination.open("x", encoding="utf8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("passed", "trajectories_replayed", "internal_and_action_sampling_steps", "maximum_score_error", "maximum_utility_replay_error")}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote-candidate-commit", required=True)
    arguments = parser.parse_args()
    run(arguments.root, arguments.remote_candidate_commit)
