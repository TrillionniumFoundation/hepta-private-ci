"""Fixed encoder/readout counterfactuals, evaluated by an independent finite DP."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..round7.dynamics import EventDynamics
from ..round7.model import load_model
from ..round7.posthoc.independent_joint_optimal import (
    Kernel, build_public_graph, forward_audit, network_greedy_actions, solve,
)
from ..round7.study import checkpoint_path
from ..round7.task import features
from .kernels import BrownianEventDynamics
from .protocol import SEEDS, configurations


def exchanged_model(anchor, mode, law):
    model = copy.deepcopy(anchor)
    core_type = EventDynamics if law == "r7-finite-v1" else BrownianEventDynamics
    core = core_type(mode, anchor.n_grid)
    core.load_state_dict(anchor.core.state_dict())
    model.core, model.mode = core, mode
    model.eval()
    return model


@torch.no_grad()
def batched_kernel(model, graph, batch_size=32):
    inputs = torch.tensor(np.stack([features(s) for s in graph.states]), dtype=torch.float64)
    _, drive = model.encode(inputs)
    transitions, events = [], []
    for offset in range(0, len(inputs), batch_size):
        matrix, event = model.core.transition_matrix(drive[offset:offset + batch_size])
        transitions.append(matrix.numpy())
        events.append(event.sum(-1).numpy())
    matrix, counts = np.concatenate(transitions), np.concatenate(events)
    defect = float(np.abs(matrix.sum(-1) - 1).max())
    if defect > 2e-10 or matrix.min() < -1e-12 or not np.isfinite(matrix).all():
        raise ArithmeticError("invalid exchanged kernel")
    normalized = np.clip(matrix, 0, None)
    normalized /= normalized.sum(-1, keepdims=True)
    return Kernel(matrix, counts, model.initial()[0].numpy(), drive.numpy(), model.n_grid,
                  defect, float(np.abs(normalized - matrix).max()))


def run(root, output):
    torch.set_num_threads(1)
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    graph = build_public_graph(configurations("nominal"))
    summary = []
    started = time.perf_counter()
    with gzip.open(output / "state_records.jsonl.gz", "wt", encoding="utf8") as raw:
        for anchor_mode in ("continuous", "clocked", "first_passage"):
            for seed in SEEDS:
                path = checkpoint_path(root / "evidence", anchor_mode, "none", seed)
                anchor = load_model(path)[0]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                for law in ("r7-finite-v1", "r8-brownian-images-v1"):
                    for target in ("continuous", "clocked", "first_passage"):
                        case = f"{anchor_mode}_{seed}__{law}__{target}"
                        case_start = time.perf_counter()
                        model = exchanged_model(anchor, target, law)
                        kernel = batched_kernel(model, graph)
                        actions = network_greedy_actions(model, graph)
                        optimum = solve(graph, kernel)
                        deployed = solve(graph, kernel, policy=actions)
                        rows, occupancy, _ = forward_audit(graph, kernel, optimum, deployed)
                        no_event = solve(graph, kernel, event_price=0)
                        record = {
                            "case": case, "anchor_mode": anchor_mode, "fit_seed": seed,
                            "contract": target, "law": law, "anchor_sha256": digest,
                            "registered_return": float(deployed.initial_values.mean()),
                            "optimal_return": float(optimum.initial_values.mean()),
                            "optimality_gap": float((optimum.initial_values - deployed.initial_values).mean()),
                            "event_free_optimal_return": no_event.initial_values.tolist(),
                            "expected_events": float(np.mean([r["expected_events"] for r in rows])),
                            "expected_decisions": float(np.mean([r["expected_decisions"] for r in rows])),
                            "maximum_mass_defect": kernel.maximum_mass_error,
                            "normalization_change": kernel.maximum_deployment_normalization_change,
                            "configurations": rows, "wall_seconds": time.perf_counter() - case_start,
                        }
                        summary.append(record)
                        raw.write(json.dumps({
                            "case": case, "actions": actions.tolist(), "occupancy": occupancy.tolist(),
                            "regret": (optimum.q_after.max(-1) - np.take_along_axis(
                                optimum.q_after, actions[..., None], axis=-1)[..., 0]).tolist(),
                            "drive": kernel.drive.tolist(), "state_digests": [s.digest() for s in graph.states],
                        }, allow_nan=False) + "\n")
                        print(json.dumps({k: record[k] for k in ("case", "registered_return", "optimality_gap")}), flush=True)
    reference = np.asarray(summary[0]["event_free_optimal_return"])
    no_event_error = max(float(np.abs(np.asarray(r["event_free_optimal_return"]) - reference).max())
                         for r in summary)
    if no_event_error > 2e-9:
        raise AssertionError("sufficient-public-state event-free invariance failed")
    result = {"schema": "hepta.contract-exchange.v1", "cases": summary,
              "public_states": len(graph.states), "wall_seconds": time.perf_counter() - started,
              "event_free_optimality_invariance_max_error": no_event_error,
              "scope": "Finite projected models, fixed shared content/readout within anchor; Brownian law changes leak jointly for all three contracts."}
    (output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parents[1] / "round7"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.root, args.output)
