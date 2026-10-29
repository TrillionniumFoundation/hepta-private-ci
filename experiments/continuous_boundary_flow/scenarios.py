"""Phase-disjoint public task contexts and fixed-slot paired episode innovations."""

from dataclasses import asdict
import time

import numpy as np

from .common import named_seed, rng_for
from .math_model import TaskSpec, build_model, solve_dp


def specifications(seed, phase, count):
    if phase not in {"training", "development", "test_id", "test_ood", "diagnostic"}:
        raise ValueError("Unknown independent phase")
    rng = rng_for(seed, "contexts:" + phase)
    specs = []
    for i in range(count):
        ood = phase == "test_ood"
        # The OOD profile changes volatility, drift, costs, deadlines, and reset quality.
        # Public task parameters remain the same information for every arm.
        specs.append(
            TaskSpec(
                mu=float(
                    rng.uniform(-0.55, 0.08) if ood else rng.uniform(-0.32, -0.10)
                ),
                sigma=float(
                    rng.uniform(0.22, 0.72) if ood else rng.uniform(0.30, 0.50)
                ),
                dt=float(rng.choice([0.35, 0.65])) if ood else 0.5,
                horizon=int(rng.choice([8, 16])) if ood else 12,
                discount=float(
                    rng.uniform(0.02, 0.16) if ood else rng.uniform(0.035, 0.09)
                ),
                production_rate=float(
                    rng.uniform(0.65, 1.2) if ood else rng.uniform(0.85, 1.15)
                ),
                failure_cost=float(
                    rng.uniform(1.0, 5.5) if ood else rng.uniform(1.7, 3.3)
                ),
                maintenance_cost=float(
                    rng.uniform(0.12, 0.95) if ood else rng.uniform(0.22, 0.50)
                ),
                maintenance_reset=float(
                    rng.uniform(0.75, 1.75) if ood else rng.uniform(1.1, 1.5)
                ),
                failure_reset=float(
                    rng.uniform(0.45, 1.2) if ood else rng.uniform(0.8, 1.1)
                ),
                initial=float(
                    rng.uniform(0.3, 1.65) if ood else rng.uniform(0.75, 1.35)
                ),
            )
        )
    return specs


def load_contexts(seed, phase, count, grid=64):
    contexts = []
    for index, spec in enumerate(specifications(seed, phase, count)):
        wall, cpu = time.perf_counter(), time.process_time()
        model = build_model(spec, n_grid=grid, x_max=4.8)
        model_cost = {
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
        }
        wall, cpu = time.perf_counter(), time.process_time()
        dp = solve_dp(model)
        planning_cost = {
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
        }
        contexts.append(
            {
                "id": f"{seed}.{phase}.context{index}",
                "model": model,
                "dp": dp,
                "spec": asdict(spec),
                "index": index,
                "model_build_cost": model_cost,
                "planning_cost": planning_cost,
            }
        )
    return contexts


def episode_streams(seed, phase, context, paths):
    name = f"{phase}:context:{context['index']}:episode-streams"
    rng = rng_for(seed, name)
    initial_uniform = rng.random(paths)
    initial = np.searchsorted(
        np.cumsum(context["model"].initial_distribution), initial_uniform
    )
    slots = rng.random((context["model"].spec.horizon, paths, 6))
    return initial, slots, named_seed(seed, name)
