"""Component timings are separate benchmarks, never added to inclusive timers."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from .data import task_configuration
from .model import load_model
from .study import checkpoint_path
from .task import State, features


def timed(function, repeats=200):
    for _ in range(10):
        function()
    wall, cpu = [], []
    for _ in range(repeats):
        begin_wall, begin_cpu = time.perf_counter_ns(), time.process_time_ns()
        function()
        cpu.append(time.process_time_ns() - begin_cpu)
        wall.append(time.perf_counter_ns() - begin_wall)
    return {"repeats": repeats, "wall_ns_mean": float(np.mean(wall)),
            "wall_ns_p50_p95": np.quantile(wall, [0.5, 0.95]).tolist(),
            "process_cpu_ns_mean": float(np.mean(cpu))}


@torch.no_grad()
def profile(root, output):
    root, output = Path(root), Path(output)
    p = task_configuration(0)
    x = torch.from_numpy(features(State(p, remaining_budget=p.budget))[None, :])
    result = {"scope": "independent warm microbenchmarks, one CPU thread, not additive to rollout inclusive times",
              "models": {}, "energy_measured": False, "production_boundary_solver": False}
    for mode in ("clocked", "first_passage", "continuous", "direct", "first_passage_temperature"):
        model, metadata = load_model(checkpoint_path(root / "evidence", mode, "none", 11))
        mass = model.initial()
        content, drive = model.encode(x)
        transition, _ = model.core.transition_matrix(drive)
        q = model.values(mass, x, content)[0, 1]
        measures = {
            "content_and_drive": timed(lambda: model.encode(x)),
            "kernel_transition": timed(lambda: model.core.transition_matrix(drive)),
            "propagate_mass": timed(lambda: torch.bmm(mass[:, None, :], transition)),
            "statewise_readout_and_expectation": timed(lambda: model.values(mass, x, content)),
            "value_comparison_argmax": timed(lambda: q.argmax()),
            "categorical_draw": timed(lambda: np.searchsorted(mass[0].numpy().cumsum(), 0.37, side="right")),
        }
        if model.core.mode == "first_passage":
            generator = model.core.absorbing_generator(drive)
            measures["matrix_exponential_only"] = timed(lambda: torch.matrix_exp(generator))
        else:
            z = torch.linspace(-8, 8, model.core.n_grid * (model.core.n_grid + 1)).double()
            measures["normal_cdf_array_only"] = timed(lambda: torch.special.ndtr(z))
        result["models"][mode] = {"timings": measures, "physical": metadata["selected_physical"],
                                  "parameters": metadata["total_parameters"],
                                  "direct_unused_kernel_note": "direct bypasses core online; kernel microbenchmark is illustrative only" if mode == "direct" else None}
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    profile(args.root, args.output)


if __name__ == "__main__":
    main()
