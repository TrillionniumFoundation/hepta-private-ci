"""Fit both plan objectives and a shared critic on old development sources."""

import argparse
import json
from pathlib import Path
import time

import torch

from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .collect import collect
from .heads import fit, pick_fixed, save, select
from .train import MANIFEST_SHA, sha, write


OBSERVER_PATHS = {"primary": "abc2-runs/base-recovery-001/reward-observer.pt",
                  "secondary": "abc2-runs/qualification-001/secondary-observer.pt"}
OBSERVER_SHA = {"primary": "8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003",
                "secondary": "b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe"}


def observers(assets):
    return {name: load_reward(assets / path, expected_file_sha256=OBSERVER_SHA[name])[0]
            for name, path in OBSERVER_PATHS.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True, choices=(17, 29, 43))
    args = parser.parse_args()
    torch.set_num_threads(1)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = args.assets / "abc2-runs/source-recovery-001/source-manifest.json"
    if sha(manifest) != MANIFEST_SHA:
        raise ValueError("Source manifest changed")
    frozen = {str(p.resolve()): sha(p) for p in Path(__file__).parent.glob("*.py")}
    frozen.update({str((args.base / (profile + ".pt")).resolve()): sha(args.base / (profile + ".pt"))
                   for profile in ("supervised", "terminal_entropic_ndu")})
    write(args.output / "REGISTRATION.json", {
        "schema": "hepta.closure.factorial.development.v1", "registered_unix_ns": time.time_ns(),
        "source_sha256": frozen, "seed": args.seed,
        "fit": {"role": "forecast_fit", "start": 0, "count": 128, "scenarios": 2},
        "selection": {"role": "forecast_calibration", "start": 0, "count": 64, "scenarios": 2},
        "gate_steps": 500, "gate_profiles": ["mean", "entropic"],
        "new_source_outcomes_opened": False,
        "scope": "2x2x2 base surrogate risk / plan actual-output risk / second-action feedback",
    })
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    corpus = load_roles(args.assets / "abc2-assets/mnist", manifest,
                        roles=("forecast_fit", "forecast_calibration"))
    readers, result = observers(args.assets), {}
    for profile in ("supervised", "terminal_entropic_ndu"):
        path = args.output / profile
        path.mkdir()
        snapshot = Snapshot.load(args.base / (profile + ".pt"))
        print(json.dumps({"seed": args.seed, "base": profile, "phase": "actual_fit_tree"}), flush=True)
        fit_data = collect(snapshot, corpus, readers, path / "fit", role="forecast_fit",
                           start=0, count=128, seed=args.seed, stream="development-fit-20261025")
        gates, critic, histories = fit(fit_data, args.seed)
        del fit_data
        selection = collect(snapshot, corpus, readers, path / "selection", role="forecast_calibration",
                            start=0, count=64, seed=args.seed, stream="development-selection-20261025")
        fixed, allocation = pick_fixed(selection), pick_fixed(selection, allocation_only=True)
        save(path / "heads.pt", gates, critic, fixed, allocation)
        chosen = {}
        for gate_name, gate in gates.items():
            for dynamic in (False, True):
                indices = select(gate, critic, selection["features"], dynamic)
                value = selection["utility"]["primary"][torch.arange(len(indices)), indices]
                chosen[f"{gate_name}/{'feedback' if dynamic else 'committed'}"] = {
                    "mean_utility": float(value.mean()), "path_counts": torch.bincount(indices, minlength=21).tolist()}
        result[profile] = {"heads_sha256": sha(path / "heads.pt"), "gate_history": histories,
                           "fixed_index": fixed, "allocation_index": allocation, "selection_diagnostic": chosen}
        del selection
        print(json.dumps({"seed": args.seed, "base": profile, "phase": "complete"}), flush=True)
    write(args.output / "RESULTS.json", {"schema": "hepta.closure.factorial.development-result.v1",
        "status": "complete", "arms": result, "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu, "registration_sha256": sha(args.output / "REGISTRATION.json")})


if __name__ == "__main__":
    main()
