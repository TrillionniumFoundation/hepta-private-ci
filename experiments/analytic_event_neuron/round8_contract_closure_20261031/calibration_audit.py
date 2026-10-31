"""Independent-policy evaluation and public-state sufficiency audit for calibration."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..round7.posthoc.independent_joint_optimal import (
    build_public_graph, forward_audit, network_greedy_actions, prepare_kernel, solve,
)
from ..round7.task import ACTIONS, TaskParameters, features


def public_optimum(graph, compute_price=0.0005):
    """Scalar public-state DP, with no internal kernel, network, or event fee."""
    values = np.zeros(len(graph.states), dtype=np.float64)
    for index in reversed(graph.forward_order):
        candidates = []
        for action in np.flatnonzero(graph.legal[index]):
            reward = graph.reward[index, action] - compute_price
            future = sum(probability * values[successor]
                         for probability, successor, _ in graph.edges[index, action]
                         if successor >= 0)
            candidates.append(reward + future)
        values[index] = max(candidates)
    return values


def zero_event_price_audit(graph, kernel):
    """With a sufficient public state, random internal state cannot improve Q*."""
    public = public_optimum(graph)
    joint = solve(graph, kernel, event_price=0.0)
    error = float(np.max(np.abs(joint.value_before - public[:, None])))
    passed = error < 1e-10
    if not passed:
        raise AssertionError("zero-event-fee public sufficiency identity failed")
    return {"passed": passed, "maximum_all_public_latent_value_error": error,
            "public_optimal_mean": float(public[graph.starts].mean()),
            "joint_optimal_mean": float(joint.initial_values.mean()),
            "positive_event_fee_kernel_effect_upper_bound": 0.0002 * max(p.horizon for p in graph.configurations),
            "meaning": "finite public-state sufficiency identity, not proof of a neural head's approximation capacity"}


@torch.no_grad()
def exact_audit(model, graph, kernel, optimum, table):
    actions = network_greedy_actions(model, graph)
    comparison = solve(graph, kernel, policy=actions)
    rows, occupancy, _ = forward_audit(graph, kernel, optimum, comparison)
    inputs = torch.tensor(np.stack([features(state) for state in graph.states]), dtype=torch.float64)
    content, _ = model.encode(inputs)
    prediction = model.state_action_values(inputs, content)[:, :, 1, :].numpy()
    squared = np.where(table["legal"], (prediction - table["q_after"]) ** 2, 0.0)
    per_state = squared.sum(-1) / table["legal"].sum(-1)
    initial, focus = [], []
    for configuration, index in enumerate(graph.starts):
        mass = kernel.initial @ kernel.transition[index]
        probabilities = np.bincount(actions[index], weights=mass, minlength=len(ACTIONS))
        optimal_probabilities = np.bincount(optimum.actions[index], weights=mass, minlength=len(ACTIONS))
        initial.append({"configuration_index": configuration,
                        "greedy_action_probabilities": probabilities.tolist(),
                        "optimal_action_probabilities": optimal_probabilities.tolist()})
    for index, state in enumerate(graph.states):
        configuration = int(graph.state_configuration[index])
        mass = occupancy[index]
        if configuration not in (4, 7) or mass.sum() <= 1e-14:
            continue
        selected = optimum.q_after[index, np.arange(len(mass)), actions[index]]
        regret = optimum.q_after[index].max(-1) - selected
        focus.append({"configuration_index": configuration, "public_state_id": index,
                      "public_state_digest": state.digest(), "tick": state.tick,
                      "posterior": state.posterior, "delayed_status": state.delayed_status,
                      "ordinary_reads": state.reads, "decision_mass": float(mass.sum()),
                      "greedy_action_conditional_probabilities": (
                          np.bincount(actions[index], weights=mass, minlength=len(ACTIONS)) / mass.sum()).tolist(),
                      "optimal_action_regret_contribution": float(mass @ regret)})
    regret_total = sum(row["optimal_action_regret_sum"] for row in rows) / len(rows)
    gap = float((optimum.initial_values - comparison.initial_values).mean())
    if abs(regret_total - gap) > 1e-10:
        raise AssertionError("full four-action performance-difference identity failed")
    return {"optimal_minus_greedy_mean": gap,
            "greedy_return_mean": float(comparison.initial_values.mean()),
            "optimal_return_mean": float(optimum.initial_values.mean()),
            "occupancy_weighted_four_action_regret_sum": regret_total,
            "uniform_legal_rmse": float(np.sqrt(squared.sum() / table["legal"].sum())),
            "training_weighted_rmse": float(np.sqrt((table["weights"] * per_state).sum())),
            "deployed_occupancy_weighted_rmse": float(np.sqrt((occupancy * per_state).sum() / occupancy.sum())),
            "per_configuration": rows, "initial_decisions": initial,
            "preset4_and_7_all_visited_public_states": focus,
            "action_order": list(ACTIONS),
            "expectation": "exact finite joint kernel with sampled latent state then greedy legal action",
            "future_information_accessed_by_policy": False}


def replay_saved(output):
    """Recompute targets and stage diagnostics from saved bytes after fitting ends."""
    from ..round7.model import load_model
    from ..round7.study import checkpoint_path
    from .calibration import MODES, SEEDS, _json_write, load_calibrated

    started, cpu_started = time.perf_counter(), time.process_time()
    output, records = Path(output), []
    for mode in MODES:
        for seed in SEEDS:
            record = json.loads((output / f"calibration_{mode}_{seed}.json").read_text())
            # Stored absolute paths record the run's origin.  Resolve artifacts
            # in this checkout so the published replay is portable.
            source = checkpoint_path(Path(__file__).resolve().parents[1] / "round7/evidence", mode, "none", seed)
            if hashlib.sha256(source.read_bytes()).hexdigest() != record["source_checkpoint_sha256"]:
                raise AssertionError("original R7 checkpoint changed")
            original, _ = load_model(source)
            graph = build_public_graph([TaskParameters(**row) for row in record["public_training_configurations"]])
            original_kernel = prepare_kernel(original, graph)
            optimum = solve(graph, original_kernel)
            target_path = output / "calibration_targets" / Path(record["target_archive"]).name
            if hashlib.sha256(target_path.read_bytes()).hexdigest() != record["target_archive_sha256"]:
                raise AssertionError("target archive changed")
            with np.load(target_path, allow_pickle=False) as archive:
                table = {key: archive[key] for key in archive.files}
            q = np.where(table["legal"], optimum.q_after, 0.0)
            target_error = float(np.max(np.abs(q - table["q_after"])))
            if target_error > 1e-12:
                raise AssertionError("saved Q* table differs from independent frozen-source recursion")
            stage_rows, previous = [], original
            for stage in ("baseline", "readout", "content_readout"):
                saved = record["checkpoints"][stage]
                path = output / "calibration_models" / Path(saved["path"]).name
                if hashlib.sha256(path.read_bytes()).hexdigest() != saved["sha256"]:
                    raise AssertionError("stage checkpoint changed")
                model, metadata = load_calibrated(path)
                kernel = prepare_kernel(model, graph)
                if not np.array_equal(kernel.transition, original_kernel.transition):
                    raise AssertionError("restored model has a different cell transition")
                if stage == "baseline":
                    if not np.array_equal(network_greedy_actions(model, graph), network_greedy_actions(original, graph)):
                        raise AssertionError("baseline wrapper changed a greedy action")
                else:
                    allowed = ("readout.",) if stage == "readout" else ("content.", "readout.")
                    for name, tensor in model.state_dict().items():
                        if not name.startswith(allowed) and not torch.equal(tensor, previous.state_dict()[name]):
                            raise AssertionError(f"stage changed a frozen parameter: {name}")
                actual = exact_audit(model, graph, kernel, optimum, table)
                fields = ("optimal_minus_greedy_mean", "greedy_return_mean", "uniform_legal_rmse",
                          "training_weighted_rmse", "occupancy_weighted_four_action_regret_sum")
                error = max(abs(actual[key] - record["audits"][stage][key]) for key in fields)
                if error > 1e-12:
                    raise AssertionError("saved model does not reproduce its stage audit")
                stage_rows.append({"stage": stage, "maximum_metric_replay_error": error,
                                   "stored_parameters": sum(p.numel() for p in model.parameters()),
                                   "frozen_cell_sha256": metadata["frozen_cell_sha256"]})
                previous = model
            records.append({"mode": mode, "seed": seed, "maximum_Q_target_error": target_error,
                            "stages": stage_rows, "zero_event_price": zero_event_price_audit(graph, original_kernel)})
    report = {"passed": True, "fits": len(records), "checkpoints_replayed": 3 * len(records),
              "all_source_checkpoint_hashes_verified": True, "records": records,
              "parameter_count_definition": "stage active_parameter_count counts requires_grad tensor elements; unused Q1 output rows remain included and Q1 is not trained or evaluated",
              "wall_seconds": time.perf_counter() - started,
              "process_cpu_seconds": time.process_time() - cpu_started}
    _json_write(output / "calibration_replay_audit.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "evidence")
    args = parser.parse_args()
    torch.set_num_threads(1)
    report = replay_saved(args.output)
    print(json.dumps({key: report[key] for key in ("passed", "fits", "checkpoints_replayed", "wall_seconds")}))


if __name__ == "__main__":
    main()
