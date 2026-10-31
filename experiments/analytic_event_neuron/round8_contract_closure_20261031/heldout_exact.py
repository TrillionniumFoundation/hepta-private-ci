"""Exact heldout finite-law deployment audit, without fitting or selecting models."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..round7.posthoc.independent_joint_optimal import (
    build_public_graph, forward_audit, network_greedy_actions, prepare_kernel, solve,
)
from .calibration import load_calibrated
from .confirmation import verify_manifest
from .protocol import MODES, SEEDS, STAGES, configurations


def run(root, output):
    root, output = Path(root), Path(output)
    torch.set_num_threads(1)
    freeze = verify_manifest(root)
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    graph = build_public_graph(configurations("heldout"))
    records = []
    for mode in MODES:
        for seed in SEEDS:
            kernel = optimum = None
            for stage in STAGES:
                path = root / "evidence/calibration_models" / f"{mode}_none_{seed}_{stage}.json"
                model = load_calibrated(path)[0]
                if kernel is None:
                    kernel = prepare_kernel(model, graph)
                    optimum = solve(graph, kernel)
                actions = network_greedy_actions(model, graph)
                deployed = solve(graph, kernel, policy=actions)
                rows, _, _ = forward_audit(graph, kernel, optimum, deployed)
                record = {"mode": mode, "fit_seed": seed, "stage": stage,
                          "registered_return": float(deployed.initial_values.mean()),
                          "optimal_return": float(optimum.initial_values.mean()),
                          "optimality_gap": float(np.mean(optimum.initial_values - deployed.initial_values)),
                          "configurations": rows}
                records.append(record)
                print(json.dumps({k: v for k, v in record.items() if k != "configurations"}), flush=True)
    if verify_manifest(root) != freeze:
        raise AssertionError("frozen inputs changed during exact audit")
    result = {"schema": "hepta.heldout-exact.v1", "freeze_sha256": freeze,
              "scope": "All legal external successors and finite latent states, hard greedy deployment",
              "public_states": len(graph.states), "records": records,
              "wall_seconds": time.perf_counter() - started}
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.root, args.output)
