"""Predeclared continuous-task numerical verification and actual owner campaign."""

import argparse
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import scipy
from scipy.stats import t as student_t

from . import reference, solver
from .execution import INITIAL, execute
from .gradients import PARAMETERS, perturb, tangent
from .task import DEFAULT, payoff, payoff_gradient


ROOT = Path(__file__).parent


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def boundaries(solution, inspection):
    rows = []
    x, config, dx = solution["x"], solution["config"], solution["dx"]
    g, dg = payoff(config, x), payoff_gradient(config, x)
    for remaining in inspection:
        index = int(round(remaining / solution["dt"]))
        for mode in range(2):
            v, b = solution["values"][index, mode], solution["reset_values"][index, mode]
            actions = solution["actions"][index, mode]
            reset = np.flatnonzero(actions == 2)
            continuation = np.flatnonzero(actions == 0)
            row = dict(remaining=remaining, mode=mode, reset_value=float(b))
            if len(reset) and len(continuation):
                i = int(reset[-1])
                candidate = np.flatnonzero((actions == 1) & (np.arange(len(x)) > continuation[-1]))
                if i + 1 < len(x) and len(candidate):
                    j = int(candidate[0])
                    row.update(reset_contact=float(x[i]), stop_contact=float(x[j]),
                        reset_value_match=float(abs(v[i] - b)), stop_value_match=float(abs(v[j] - g[mode, j])),
                        reset_smooth_fit_error=float(abs((v[i + 1] - v[i]) / dx)),
                        stop_smooth_fit_error=float(abs((v[j] - v[j - 1]) / dx - dg[mode, j])))
            rows.append(row)
    return rows


def initial_mean(solution):
    return float(np.mean([np.interp(x, solution["x"], solution["values"][-1, mode]) for x, mode in INITIAL]))


def interval(values):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    radius = float(student_t.ppf(.975, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
    return dict(mean=mean, t95=[mean - radius, mean + radius], independent_worlds=len(values),
                scope="Conditional paired-world Monte Carlo interval, no discretization or architecture uncertainty")


def run(output):
    output.mkdir(exist_ok=False)
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen source changed: {name}")
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    started, wall = time.process_time(), time.perf_counter()
    numeric, gradient_rows, selected, profiles = [], [], [], []
    heat_check = reference.semigroup_check()
    for profile, sigma in enumerate(protocol["task"]["sigma_profiles"]):
        config = copy.deepcopy(DEFAULT)
        config["sigma"] = sigma
        previous, finest = None, None
        levels = []
        for dx, dt in protocol["meshes"]:
            primary, independent = solver.solve(config, dx, dt), reference.solve(config, dx, dt)
            kernel = reference.heat(np.eye(len(primary["x"])), sigma, config["upper"] - config["lower"], dt)
            row = dict(sigma=sigma, dx=dx, dt=dt,
                fd_reference_max_value_gap=float(abs(primary["values"] - independent["values"]).max()),
                fd_initial_mean=initial_mean(primary), reference_initial_mean=initial_mean(independent),
                lcp_residual=primary["maximum_lcp_residual"],
                heat_kernel_min=float(kernel.min()), heat_mass_error=float(abs(kernel.sum(0) - 1).max()),
                boundaries=boundaries(primary, protocol["boundary_inspection_times"]))
            if previous is not None:
                row["consecutive_mesh_gap"] = float(abs(primary["values"][::2, :, ::2] - previous["values"]).max())
            levels.append(row)
            previous, finest = primary, (primary, independent)
        primary, independent = finest
        numeric.append(dict(sigma=sigma, levels=levels))
        dx, dt = protocol["gradient"]["mesh"]
        gbase = solver.solve(config, dx, dt)
        for parameter in PARAMETERS:
            derivative = tangent(gbase, parameter)
            step = protocol["gradient"]["step"]
            plus, minus = (solver.solve(perturb(config, parameter, sign * step), dx, dt) for sign in (1, -1))
            fd = (plus["values"] - minus["values"]) / (2 * step)
            active_changes = int(np.sum(plus["actions"] != gbase["actions"]) + np.sum(minus["actions"] != gbase["actions"]))
            gradient_rows.append(dict(sigma=sigma, parameter=parameter, active_set_changes=active_changes,
                maximum_scaled_error=float(np.max(abs(derivative - fd) / (1 + abs(fd)))),
                qualifies_smooth_active_branch=active_changes == 0))
        family = []
        dx, dt = protocol["meshes"][-1]
        for thresholds in protocol["threshold_family"]:
            candidate = reference.solve_fixed(config, dx, dt, thresholds)
            family.append(dict(thresholds=thresholds, model_mean_utility=initial_mean(candidate)))
        best = max(family, key=lambda row: row["model_mean_utility"])
        selected.append(dict(sigma=sigma, family=family, selected=best,
                             fd_model_utility=initial_mean(primary), reference_model_utility=initial_mean(independent)))
        profiles.append((primary, independent, best["thresholds"]))
    save(output / "MODEL_SELECTION.json", dict(source_freeze=freeze, selections=selected,
        timing="All model-based fixed selections persisted before any owner outcome is opened."))
    raw_manifest, owner_summary = [], []
    count = protocol["owner"]["worlds_per_profile"]
    for profile, (primary, independent, thresholds) in enumerate(profiles):
        outcomes = {arm: [] for arm in protocol["owner"]["arms"]}
        for begin in range(0, count, 128):
            raw = []
            for world in range(begin, min(begin + 128, count)):
                seed = protocol["owner"]["seed_namespace"] + profile * 100000 + world
                initial = INITIAL[world % len(INITIAL)]
                for arm, solution, policy, threshold in (
                        ("free_fd", primary, "free", None),
                        ("free_reference", independent, "free", None),
                        ("fixed_selected", primary, "fixed", thresholds),
                        ("stop_now", primary, "stop_now", None)):
                    row = execute(solution, seed, initial, policy, threshold)
                    row.update(arm=arm, sigma=primary["config"]["sigma"], world=world)
                    if row["elapsed_steps"] + row["remaining_steps"] != len(primary["times"]) - 1:
                        raise RuntimeError("Owner discarded reset remaining time")
                    outcomes[arm].append(row)
                    raw.append(row)
            data = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in raw).encode()
            packed = io.BytesIO()
            with gzip.GzipFile(filename="", mode="wb", fileobj=packed, mtime=0, compresslevel=9) as stream:
                stream.write(data)
            path = output / f"owner_profile{profile}_part{begin // 128:03d}.jsonl.gz"
            compressed = packed.getvalue()
            if len(compressed) > 512000:
                raise RuntimeError("Raw part exceeds publication file bound")
            with path.open("xb") as stream:
                stream.write(compressed)
            raw_manifest.append(dict(path=path.name, rows=len(raw), raw_sha256=hashlib.sha256(data).hexdigest(),
                raw_bytes=len(data), sha256=hashlib.sha256(compressed).hexdigest(), bytes=len(compressed)))
        arms = {}
        for arm, records in outcomes.items():
            arms[arm] = dict(mean_utility=float(np.mean([r["utility"] for r in records])),
                mean_propensity_utility=float(np.mean([r["propensity_utility"] for r in records])),
                mean_success=float(np.mean([r["success"] for r in records])),
                mean_fee=float(np.mean([r["fee"] for r in records])),
                mean_wait_steps=float(np.mean([r["actions"].count("W") for r in records])),
                mean_reset_count=float(np.mean([r["actions"].count("R") for r in records])))
        comparisons = {}
        for comparator in ("free_reference", "fixed_selected", "stop_now"):
            comparisons[comparator] = {metric: interval([a[metric] - b[metric] for a, b in zip(outcomes["free_fd"], outcomes[comparator])])
                                      for metric in ("utility", "propensity_utility")}
        owner_summary.append(dict(sigma=primary["config"]["sigma"], arms=arms, comparisons=comparisons,
                                  selected_fixed_thresholds=thresholds))
    finest_rows = [row["levels"][-1] for row in numeric]
    smooth = [row for level in finest_rows for row in level["boundaries"] if "reset_contact" in row]
    qualifying_gradients = [row for row in gradient_rows if row["qualifies_smooth_active_branch"]]
    gates = dict(lcp_residual=max(r["lcp_residual"] for r in finest_rows) < protocol["gates"]["lcp_residual"],
        finest_reference_value_gap=max(r["fd_reference_max_value_gap"] for r in finest_rows) < protocol["gates"]["finest_reference_value_gap"],
        finest_consecutive_mesh_gap=max(r["consecutive_mesh_gap"] for r in finest_rows) < protocol["gates"]["finest_consecutive_mesh_gap"],
        refinement_reduces_reference_gap=all(row["levels"][-1]["fd_reference_max_value_gap"] < row["levels"][0]["fd_reference_max_value_gap"] for row in numeric),
        finest_smooth_fit_error=bool(smooth) and max(max(r["reset_smooth_fit_error"], r["stop_smooth_fit_error"]) for r in smooth) < protocol["gates"]["finest_smooth_fit_error"],
        contact_value_error=bool(smooth) and max(max(r["reset_value_match"], r["stop_value_match"]) for r in smooth) < protocol["gates"]["contact_value_error"],
        heat_semigroup=max(heat_check.values()) < protocol["gates"]["heat_cosine_or_semigroup_error"],
        heat_positivity=min(r["heat_kernel_min"] for r in finest_rows) > -protocol["gates"]["heat_negative_kernel_tolerance"],
        heat_mass=max(r["heat_mass_error"] for r in finest_rows) < protocol["gates"]["heat_cosine_or_semigroup_error"],
        smooth_branch_gradient=bool(qualifying_gradients) and all(row["maximum_scaled_error"] < protocol["gates"]["smooth_branch_gradient_error"] for row in qualifying_gradients))
    result = dict(schema="hcsn-r18-continuous-task-results-v1", source_freeze=freeze, gates=gates,
        numeric=numeric, gradients=gradient_rows, qualifying_gradient_case_count=len(qualifying_gradients),
        changed_gradient_case_count=len(gradient_rows) - len(qualifying_gradients),
        heat_semigroup=heat_check, owner=owner_summary,
        model_selection=selected, raw_manifest=raw_manifest,
        scope=protocol["scope"], no_continuous_crossing_execution=True, production_activation=False,
        cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__))
    save(output / "RESULTS.json", result)
    print(json.dumps(dict(gates=gates, profiles=owner_summary, cpu_seconds=result["cpu_seconds"]), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
