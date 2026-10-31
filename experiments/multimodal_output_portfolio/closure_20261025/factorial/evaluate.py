"""Freeze and execute the complete factorial on its newly assigned sources."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..sources import load_registered
from ...abc_recovery.trees import PLANS
from ...v7.snapshot import Snapshot
from .collect import collect
from .develop import OBSERVER_PATHS, observers
from .heads import load, select
from .train import sha, write


SEEDS = (17, 29, 43)
BASES = ("supervised", "terminal_entropic_ndu")


def freeze(assets, runs, allocation, output):
    area = Path(__file__).resolve().parents[2]
    candidates = list(Path(__file__).parent.glob("*.py")) + [area / "closure_20261025/sources.py"]
    for folder in ("abc_recovery", "abc_next", "v6", "v7"):
        candidates.extend((area / folder).glob("*.py"))
    candidates += [assets / p for p in OBSERVER_PATHS.values()]
    models = []
    for seed in SEEDS:
        base_dir = (assets / "abc2-runs/base-recovery-001" if seed == 17 else runs / f"base-seed-{seed}")
        development = runs / f"development-seed-{seed}"
        if json.loads((development / "RESULTS.json").read_text())["status"] != "complete":
            raise ValueError("All development arms must finish before source access")
        for base in BASES:
            snapshot, heads = base_dir / (base + ".pt"), development / base / "heads.pt"
            candidates += [snapshot, heads]
            models.append({"seed": seed, "base": base, "snapshot": str(snapshot.resolve()),
                           "heads": str(heads.resolve())})
    protocol = {"schema": "hepta.closure.factorial.evaluation.v1", "study": "factorial",
        "frozen_unix_ns": time.time_ns(), "source_allocation_sha256": sha(allocation),
        "frozen_candidate_sha256": {str(p.resolve()): sha(p) for p in sorted(set(candidates))},
        "models": models, "seeds": SEEDS, "base_profiles": BASES,
        "gate_profiles": ["mean", "entropic"], "dynamic": [False, True],
        "source_role": "closure_factorial", "pair_count": 256, "views": 8, "scenarios": 2,
        "plans": PLANS, "risk_aversion": 2., "nominal_action_price": .002,
        "stream": "final-fresh-factorial-20261025",
        "primary": "Seven factorial contrasts of raw output CE under the primary independent observer",
        "contrasts": "Average signed cell CE: three main, three two-factor and one three-factor effects",
        "inference": {"bootstrap": "source-pair clustered, preserve all seeds/views/scenarios/cells jointly",
                      "replicates": 4096, "seed": 2026102503,
                      "level_per_contrast": 1 - .05 / 7,
                      "scope": "Conditional on three fitted seeds; Bonferroni seven contrasts, nominal bootstrap"},
        "secondary": "Independent second observer, exact success, nominal action price, per-seed effects",
        "oracle": "Realized private-target/future maximum over 21 actual outputs; not an achievable policy",
        "timing": "Offline full enumeration plus fitting; no online cost-superiority claim",
        "base_objective": "Matched teacher-forced surrogate mean vs conditional latent-noise entropic loss",
        "gate_objective": "Finite actual-output plan probabilities, mean vs joint entropic moment",
        "dynamic_factor": "Commit same learned first action; reselect stop/second action from current public draft",
        "all_eight_views_retained": True, "no_new_source_selection_or_retraining": True}
    write(output, protocol)
    return protocol


def run(assets, allocation, protocol_path, output):
    torch.set_num_threads(1)
    protocol = json.loads(protocol_path.read_text())
    output.mkdir(parents=True, exist_ok=False)
    write(output / "ACCESS.json", {"protocol_sha256": sha(protocol_path), "registered_unix_ns": time.time_ns(),
        "source_role": "closure_factorial", "start": 0, "count": 256})
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    corpus = load_registered(assets / "abc2-assets/mnist",
                            assets / "abc2-runs/source-recovery-001/source-manifest.json",
                            allocation, "factorial", protocol_path)
    readers = observers(assets)
    cells, utilities, successes, paths, baselines, baseline_values = [], [], [], [], [], []
    for model_spec in protocol["models"]:
        seed, base = model_spec["seed"], model_spec["base"]
        print(json.dumps({"phase": "enumerating_new_sources", "seed": seed, "base": base}), flush=True)
        snapshot = Snapshot.load(model_spec["snapshot"])
        gates, critic, fixed, allocation_index = load(model_spec["heads"])
        data = collect(snapshot, corpus, readers, output / f"seed-{seed}" / base,
                       role="closure_factorial", start=0, count=256, seed=seed, stream=protocol["stream"])
        def values(metric, indices):
            return np.stack([data[metric][reader][torch.arange(len(indices)), indices].numpy()
                             .reshape(8, 256, 2).transpose(1, 0, 2) for reader in readers])
        for gate_name, gate in gates.items():
            for dynamic in (False, True):
                chosen = select(gate, critic, data["features"], dynamic)
                cells.append({"seed": seed, "base": base, "gate": gate_name, "dynamic": dynamic})
                utilities.append(values("utility", chosen))
                successes.append(values("success", chosen))
                paths.append(chosen.numpy().reshape(8, 256, 2).transpose(1, 0, 2))
        for name, indices in (("strong_fixed", torch.full((4096,), fixed)),
                              ("allocation", torch.full((4096,), allocation_index)),
                              ("private_realized_oracle", data["utility"]["primary"].argmax(1))):
            baselines.append({"seed": seed, "base": base, "policy": name})
            baseline_values.append(values("utility", indices))
        del data
    with (output / "selected.npz").open("xb") as stream:
        np.savez_compressed(stream, utility=np.stack(utilities), success=np.stack(successes),
                            paths=np.stack(paths), baseline_utility=np.stack(baseline_values))
    write(output / "COMPLETION.json", {"schema": "hepta.closure.factorial.completion.v1", "status": "complete",
        "protocol_sha256": sha(protocol_path), "selected_sha256": sha(output / "selected.npz"),
        "independent_source_pairs": 256, "cells": cells, "baselines": baselines, "observers": list(readers),
        "actual_outputs_generated_and_reopened": 6 * 256 * 8 * 2 * 21,
        "policy_selected_rows": 24 * 256 * 8 * 2,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "source_ids_sha256": json.loads(allocation.read_text())["roles"]["factorial"]["source_ids_sha256"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze(args.assets, args.runs, args.allocation, args.protocol)
    else:
        run(args.assets, args.allocation, args.protocol, args.output)
