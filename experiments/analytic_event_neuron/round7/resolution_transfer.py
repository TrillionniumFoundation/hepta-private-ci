"""Read-only checkpoint resolution transfer with unchanged learned parameters.

This is a numerical deployment diagnostic, not retraining or a continuous-OU
certificate. Grid buffers are rebuilt; only named Parameters are copied.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import ndtr
import torch

from .data import task_configuration
from .joint_control import build_graph
from .model import JointCell, load_model
from . import oracle
from .task import ACTIONS, features, generate_episode, initial_state, legal_actions, step


def parameter_sha256(model):
    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        array = parameter.detach().cpu().contiguous().numpy()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(array.dtype).encode("ascii") + b"\0")
        digest.update(str(array.shape).encode("ascii") + b"\0")
        digest.update(array.tobytes())
    return digest.hexdigest()


def transfer_parameters_only(source, grid):
    """Keep the encoder, readout and physical scalar parameters bit-identical."""
    with torch.random.fork_rng(devices=[]):
        target = JointCell(source.mode, n_grid=grid, hidden=source.hidden)
    source_parameters = dict(source.named_parameters())
    target_parameters = dict(target.named_parameters())
    if source_parameters.keys() != target_parameters.keys():
        raise ValueError("resolution transfer changed parameter names")
    with torch.no_grad():
        for name, parameter in target_parameters.items():
            if parameter.shape != source_parameters[name].shape:
                raise ValueError(f"resolution-dependent learned parameter: {name}")
            parameter.copy_(source_parameters[name])
    target.eval()
    if parameter_sha256(target) != parameter_sha256(source):
        raise AssertionError("learned parameters changed during transfer")
    return target


def public_replays(configuration_indices, seed_start, count):
    """Identical observed input sequences, chosen by a public oracle policy.

    These replays diagnose the cell law. They are not trajectories of each
    transferred learned policy; policy returns are evaluated separately.
    """
    records = []
    for i in range(count):
        configuration_index = configuration_indices[i % len(configuration_indices)]
        episode = generate_episode(seed_start + i, task_configuration(configuration_index))
        state = initial_state(episode)
        inputs, digests, actions = [], [], []
        while not state.terminated:
            inputs.append(features(state).tolist())
            digests.append(state.digest())
            action = oracle.best_action(state)
            if action not in legal_actions(state):
                raise AssertionError("reference replay requested an illegal action")
            actions.append(action)
            state = step(state, action, episode).state
        records.append({"seed": seed_start + i, "configuration_index": configuration_index,
                        "inputs": inputs, "public_state_digests": digests, "actions": actions})
    return records


@torch.no_grad()
def prepare_graph(model, graph):
    content, drive = model.encode(graph.inputs)
    if model.mode == "direct":
        transition = torch.eye(model.core.n_states, dtype=torch.float64).expand(len(graph.states), -1, -1)
        events = torch.zeros(len(graph.states), model.core.n_states, 2, dtype=torch.float64)
    else:
        transition, events = model.core.transition_matrix(drive)
    prediction = model.state_action_values(graph.inputs, content)
    return transition, events, prediction, drive


@torch.no_grad()
def exact_policy_metrics(model, graph, prepared, *, policy="soft", head=1,
                         temperature=0.12, compute_price=0.0005, event_price=0.0002):
    """Finite-DAG expected return, decision count and event count together."""
    transition, events, prediction, _ = prepared
    selected = prediction[:, :, head, :].masked_fill(~graph.legal[:, None, :], -1e9)
    if policy == "soft":
        probabilities = torch.softmax(selected / temperature, dim=-1)
    elif policy == "greedy":
        probabilities = torch.nn.functional.one_hot(selected.argmax(-1), len(ACTIONS)).double()
    else:
        raise ValueError(policy)
    count, latent = len(graph.states), model.core.n_states
    values = torch.zeros(count + 1, latent, 3, dtype=torch.float64)
    for ids, successors, weights in graph.layers:
        continuation = (values[successors] * weights[:, :, :, None, None]).sum(2).transpose(1, 2)
        immediate = graph.immediate[ids, None, :].expand(-1, latent, -1)
        q = torch.stack((continuation[:, :, :, 0] + immediate - compute_price,
                         continuation[:, :, :, 1] + 1.0,
                         continuation[:, :, :, 2]), dim=-1)
        after = (probabilities[ids, :, :, None] * q).sum(2)
        before = torch.bmm(transition[ids], after)
        event_count = events[ids].sum(-1)
        before[:, :, 0] -= event_price * event_count
        before[:, :, 2] += event_count
        values[ids] = before
    starts = torch.tensor(graph.initial_indices)
    value = (values[starts] * model.initial(len(starts))[:, :, None]).sum(1).mean(0)
    registered, decisions, event_count = (float(x) for x in value)
    return {"registered_return": registered,
            "task_return_before_internal_proxy_fees": registered + compute_price * decisions + event_price * event_count,
            "expected_decisions": decisions, "expected_events": event_count,
            "events_per_decision": event_count / decisions if decisions else 0.0,
            "compute_proxy_fee": compute_price * decisions,
            "event_proxy_fee": event_price * event_count,
            "policy": policy, "head": head, "temperature": temperature if policy == "soft" else None}


@torch.no_grad()
def replay_metrics(model, records):
    physical = {name: float(value.detach()) for name, value in model.core.physical_parameters().items()}
    rows = []
    all_events, all_ticks = 0.0, 0
    active_weight, artificial_variance = 0.0, 0.0
    projected_tail = 0.0
    maximum_mass_error = 0.0
    for record in records:
        mass = model.initial(1)
        total = 0.0
        path = []
        for inputs in record["inputs"]:
            x = torch.tensor([inputs], dtype=torch.float64)
            _, drive = model.encode(x)
            if model.mode in ("first_passage", "first_passage_temperature"):
                drift = drive[:, None] - physical["leak"] * model.core.active_grid()[None, :]
                spacing = 2.0 * physical["boundary"] / (model.n_grid + 1)
                active = mass[:, :model.n_grid]
                artificial_variance += float((active * drift.abs() * spacing / physical["diffusion"]**2).sum())
                active_weight += float(active.sum())
            if model.mode == "continuous":
                grid = model.core.active_grid().numpy()
                leak, sigma, b = physical["leak"], physical["diffusion"], physical["boundary"]
                mean = np.exp(-leak) * grid + (-np.expm1(-leak) / leak) * float(drive[0])
                sd = sigma * np.sqrt(-np.expm1(-2.0 * leak) / (2.0 * leak))
                tails = ndtr((-b - mean) / sd) + ndtr((mean - b) / sd)
                projected_tail += float(mass[0, :model.n_grid].numpy() @ tails)
            mass, events, _ = model.advance(mass, x)
            count = float(events.sum())
            total += count
            maximum_mass_error = max(maximum_mass_error, abs(float(mass.sum()) - 1.0))
            path.append({"drive": float(drive[0]), "expected_events_plus_minus": events[0].tolist(),
                         "features": model.core.state_features(mass)[0].tolist()})
        all_events += total
        all_ticks += len(record["inputs"])
        rows.append({"seed": record["seed"], "expected_events": total, "ticks": len(path), "path": path})
    return {"expected_events": all_events, "ticks": all_ticks,
            "events_per_tick": all_events / all_ticks if all_ticks else 0.0,
            "active_mass_weighted_extra_variance_over_sigma_squared": artificial_variance / active_weight if active_weight else None,
            "mean_continuous_tail_projection_probability": projected_tail / all_ticks if model.mode == "continuous" and all_ticks else None,
            "maximum_mass_error": maximum_mass_error, "traces": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", type=Path, nargs="+", required=True)
    parser.add_argument("--grids", type=int, nargs="+", default=[15, 31, 63])
    parser.add_argument("--config-indices", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--trace-seed", type=int, default=430000)
    parser.add_argument("--trace-count", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.trace_count < 1 or any(n < 5 or n % 2 != 1 for n in args.grids):
        raise ValueError("positive trace count and odd voltage grids >=5 are required")
    graph = build_graph([task_configuration(i) for i in args.config_indices])
    traces = public_replays(args.config_indices, args.trace_seed, args.trace_count)
    records = []
    for checkpoint in args.checkpoints:
        original_bytes = checkpoint.read_bytes()
        source, source_metadata = load_model(checkpoint)
        source_digest = parameter_sha256(source)
        source_grids = list(dict.fromkeys([source.n_grid] + args.grids))
        results = []
        for grid in source_grids:
            started = time.perf_counter()
            model = transfer_parameters_only(source, grid)
            prepared = prepare_graph(model, graph)
            event_from_zero = prepared[1][:, grid // 2, :]
            physical = {key: float(value.detach()) for key, value in model.core.physical_parameters().items()}
            policies = {
                "joint_soft": exact_policy_metrics(model, graph, prepared, policy="soft", head=1),
                "joint_greedy": exact_policy_metrics(model, graph, prepared, policy="greedy", head=1),
                "one_step_greedy": exact_policy_metrics(model, graph, prepared, policy="greedy", head=0),
            }
            results.append({"grid": grid, "parameter_sha256": parameter_sha256(model),
                            "physical_parameters": physical,
                            "one_step_events_from_zero": event_from_zero.tolist(),
                            "mean_one_step_events_from_zero": float(event_from_zero.sum(-1).mean()),
                            "maximum_transition_mass_error": float((prepared[0].sum(-1) - 1.0).abs().max()),
                            "policy_metrics": policies, "common_public_replay": replay_metrics(model, traces),
                            "diagnostic_wall_seconds": time.perf_counter() - started})
        baseline = results[0]
        for result in results:
            delta = np.asarray(result["one_step_events_from_zero"]) - np.asarray(baseline["one_step_events_from_zero"])
            result["relative_to_source_grid"] = {
                "maximum_absolute_one_step_event_probability_change": float(np.abs(delta).max()),
                "mean_one_step_event_count_change": result["mean_one_step_events_from_zero"] - baseline["mean_one_step_events_from_zero"],
                "replay_events_per_tick_change": result["common_public_replay"]["events_per_tick"] - baseline["common_public_replay"]["events_per_tick"],
                "registered_return_change": {key: metric["registered_return"] - baseline["policy_metrics"][key]["registered_return"] for key, metric in result["policy_metrics"].items()},
            }
        if checkpoint.read_bytes() != original_bytes:
            raise AssertionError("source checkpoint changed during audit")
        records.append({"checkpoint": str(checkpoint), "checkpoint_sha256": hashlib.sha256(original_bytes).hexdigest(),
                        "source_configuration": source.configuration(), "source_metadata": source_metadata,
                        "learned_parameter_sha256": source_digest,
                        "source_checkpoint_unchanged": True, "resolutions": results})
        print(json.dumps({"checkpoint": str(checkpoint), "grids": source_grids,
                          "joint_greedy_returns": [row["policy_metrics"]["joint_greedy"]["registered_return"] for row in results]}), flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "runtime_source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                         for name in ("dynamics.py", "temperature.py", "model.py", "joint_control.py", "task.py", "oracle.py", "resolution_transfer.py")},
              "scope": "Unchanged learned parameters; rebuilt mesh buffers; no retraining, no checkpoint selection and no continuous-OU certification.",
              "configuration_indices": args.config_indices, "public_states": len(graph.states),
              "public_state_digests": [state.digest() for state in graph.states],
              "common_replay": traces,
              "replay_input_sha256": hashlib.sha256(json.dumps(traces, sort_keys=True).encode()).hexdigest(),
              "fee_coefficients": {"compute_price": 0.0005, "event_price": 0.0002},
              "checkpoints": records,
              "interpretation": ["Return differences are deployment sensitivity at fixed learned parameters, not gains from retraining.",
                                 "The common input replay is a dynamics diagnostic; each learned policy's own action-dependent paths are integrated separately in policy_metrics.",
                                 "Greedy policy discontinuities can amplify small state/value changes; grid convergence is not established by one favorable transfer.",
                                 "Short configuration subsets must be named explicitly and do not establish robustness on all training/evaluation configurations.",
                                 "The FPT/temperature upwind extra-variance ratio is a diagnostic of the underlying generator; the temperature control itself is not a diffusion semigroup."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

