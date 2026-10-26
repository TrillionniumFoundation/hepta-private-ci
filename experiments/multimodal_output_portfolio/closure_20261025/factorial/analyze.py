"""Predeclared source-clustered factorial contrasts with explicit interaction scaling."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from .heads import ACTION_PRICE, GAMMA, PLANS
from .train import sha, write


NAMES = ("base_risk", "gate_risk", "dynamic")
CONTRASTS = tuple(c for size in (1, 2, 3) for c in itertools.combinations(range(3), size))


def signs(cell):
    return np.array([1 if cell["base"] == "terminal_entropic_ndu" else -1,
                     1 if cell["gate"] == "entropic" else -1,
                     1 if cell["dynamic"] else -1])


def contrast_weights(cells):
    design = np.stack([signs(cell) for cell in cells])
    return np.stack([2 * np.prod(design[:, columns], axis=1) / len(cells) for columns in CONTRASTS])


def cell_ce(values):
    return -np.log(np.exp(-GAMMA * values).mean(axis=(1, 2, 3))) / GAMMA


def analyze(directory, protocol_path):
    receipt = json.loads((directory / "COMPLETION.json").read_text())
    protocol = json.loads(protocol_path.read_text())
    if receipt["protocol_sha256"] != sha(protocol_path) or receipt["selected_sha256"] != sha(directory / "selected.npz"):
        raise ValueError("Closed factorial evidence changed")
    with np.load(directory / "selected.npz", allow_pickle=False) as saved:
        utility, success, paths, baseline = (saved[k] for k in ("utility", "success", "paths", "baseline_utility"))
    if utility.shape != (24, 2, 256, 8, 2) or success.shape != utility.shape or paths.shape != (24, 256, 8, 2):
        raise ValueError("Incomplete factorial census")
    expected = {(seed, base, gate, dynamic) for seed in (17, 29, 43)
                for base in ("supervised", "terminal_entropic_ndu") for gate in ("mean", "entropic")
                for dynamic in (False, True)}
    if {(c["seed"], c["base"], c["gate"], c["dynamic"]) for c in receipt["cells"]} != expected:
        raise ValueError("Missing/repeated factorial cell")
    weights = contrast_weights(receipt["cells"])
    inference = protocol["inference"]
    rng = np.random.default_rng(inference["seed"])
    source_weights = rng.multinomial(256, np.full(256, 1 / 256), size=inference["replicates"]) / 256
    report = {"status": "complete", "independent_source_pairs": 256, "fitted_seeds": [17, 29, 43],
              "observed_rows_are_not_independent_samples": True,
              "interaction_scale": "Average parity contrast, same 2/8 normalization as main effects; not unscaled difference-in-differences",
              "bootstrap_scope": inference, "primary_contrasts": {}, "secondary_contrasts": {}, "cells": []}
    for observer_index, name in enumerate(receipt["observers"]):
        u = utility[:, observer_index].astype(np.float64)
        moments = np.exp(-GAMMA * u).mean(axis=(2, 3))
        points = weights @ cell_ce(u)
        draws = weights @ (-np.log(moments @ source_weights.T) / GAMMA)
        tail = (1 - inference["level_per_contrast"]) / 2 if observer_index == 0 else .025
        target = report["primary_contrasts" if observer_index == 0 else "secondary_contrasts"]
        for index, columns in enumerate(CONTRASTS):
            bounds = np.quantile(draws[index], (tail, 1 - tail))
            target["x".join(NAMES[c] for c in columns)] = {"CE_effect": float(points[index]),
                "lower": float(bounds[0]), "upper": float(bounds[1]), "nominal_level": 1 - 2 * tail,
                "success_effect": float(weights[index] @ success[:, observer_index].mean(axis=(1, 2, 3))),
                "positive_quality_gate": bool(bounds[0] > 0),
                "per_seed": {str(seed): float(3 * weights[index, [c["seed"] == seed for c in receipt["cells"]]]
                     @ cell_ce(u[[c["seed"] == seed for c in receipt["cells"]]])) for seed in (17, 29, 43)}}
    lengths = np.array([len(plan) for plan in PLANS])[paths]
    for index, cell in enumerate(receipt["cells"]):
        report["cells"].append({**cell,
            "primary_CE": float(cell_ce(utility[index:index + 1, 0])[0]),
            "primary_success": float(success[index, 0].mean()),
            "secondary_CE": float(cell_ce(utility[index:index + 1, 1])[0]),
            "mean_continuation_actions": float(lengths[index].mean()),
            "nominal_action_price_CE": float(cell_ce((utility[:, 0] - ACTION_PRICE * lengths)[index:index + 1])[0]),
            "path_counts": np.bincount(paths[index].flatten(), minlength=21).tolist()})
    report["baselines"] = [{**row, "primary_CE": float(cell_ce(baseline[i:i + 1, 0])[0]),
                              "secondary_CE": float(cell_ce(baseline[i:i + 1, 1])[0])}
                             for i, row in enumerate(receipt["baselines"])]
    report["oracle_scope"] = protocol["oracle"]
    report["cost_scope"] = protocol["timing"]
    report["evidence"] = {"completion_sha256": sha(directory / "COMPLETION.json"),
                           "analysis_source_sha256": sha(__file__)}
    write(directory / "RESULTS.json", report)
    print(json.dumps(report["primary_contrasts"], sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.directory, args.protocol)
