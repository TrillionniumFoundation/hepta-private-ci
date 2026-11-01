"""Post-outcome positive-reference/event-jump repair, frozen before these checks."""

import argparse
import copy
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import scipy

from .campaign import boundaries, initial_mean, interval, save
from .execution import INITIAL
from .followup_execution import execute
from . import jump_solver, positive_reference, solver
from .task import DEFAULT


ROOT = Path(__file__).parent


def run(output):
    output.mkdir(exist_ok=False)
    freeze = json.loads((ROOT / "SOURCE_FREEZE_FOLLOWUP.json").read_text())
    inherited = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for manifest in (freeze, inherited):
        for name, expected in manifest["files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Frozen source changed: {name}")
    protocol = json.loads((ROOT / "FOLLOWUP_PROTOCOL.json").read_text())
    started, wall = time.process_time(), time.perf_counter()
    numerical, selections, profiles = [], [], []
    thresholds = [[(a, b), (c, d)] for a, b, c, d in itertools.product(
        protocol["fixed_mode0_reset_thresholds"], protocol["fixed_mode0_stop_thresholds"],
        protocol["fixed_mode1_reset_thresholds"], protocol["fixed_mode1_stop_thresholds"])]
    for sigma in protocol["sigma_profiles"]:
        config = copy.deepcopy(DEFAULT)
        config["sigma"] = sigma
        levels, previous = [], None
        for dx, dt in protocol["meshes"]:
            primary = jump_solver.solve(config, dx, dt)
            reference = positive_reference.solve(config, dx, dt)
            operator = reference["operator"]
            alternate = positive_reference.kernel(sigma, config["upper"] - config["lower"], len(primary["x"]) - 1, dt, 16)
            grid = primary["x"] - config["lower"]
            cosine = np.cos(3 * np.pi * grid / (config["upper"] - config["lower"]))
            long = positive_reference.kernel(sigma, 8., len(grid) - 1, .37)
            exact_cosine = cosine * np.exp(-.5 * sigma ** 2 * (3 * np.pi / 8) ** 2 * .37)
            cosine_error = float(abs(positive_reference.heat(cosine, long) - exact_cosine).max())
            first_jump = primary["lag"]
            wrong = solver.solve(config, dx, dt) if dx == protocol["meshes"][0][0] else None
            row = dict(sigma=sigma, dx=dx, dt=dt,
                primary_reference_max_gap=float(abs(primary["values"] - reference["values"]).max()),
                lcp_residual=primary["maximum_lcp_residual"], minimum_kernel_weight=operator["minimum_weight"],
                kernel_mass_error=operator["mass_error"], log_omitted_image_tail_bound=operator["log_omitted_image_tail_bound"],
                quadrature_difference=float(abs(operator["weights"] - alternate["weights"]).max()),
                cosine_consistency_error=cosine_error, boundaries=boundaries(primary, protocol["boundary_inspection_times"]),
                jump_records=primary["jump_records"], fd_model_utility=initial_mean(primary), reference_model_utility=initial_mean(reference))
            if wrong is not None:
                row["old_preview_first_jump_overestimate"] = float(np.max(wrong["values"][first_jump] - primary["values"][first_jump]))
            if previous is not None:
                row["consecutive_mesh_gap"] = float(abs(primary["values"][::2, :, ::2] - previous["values"]).max())
            levels.append(row)
            previous = primary
        numerical.append(dict(sigma=sigma, levels=levels))
        dx, dt = protocol["fixed_selection_mesh"]
        family = []
        for threshold in thresholds:
            candidate = positive_reference.solve(config, dx, dt, threshold)
            family.append(dict(thresholds=threshold, model_mean_utility=initial_mean(candidate)))
        best = max(family, key=lambda row: row["model_mean_utility"])
        selections.append(dict(sigma=sigma, family=family, selected=best))
        profiles.append((primary, reference, best["thresholds"]))
    save(output / "MODEL_SELECTION.json", dict(source_freeze=freeze, selections=selections,
        timing="All81 mode-conditioned candidate selections persisted before fresh followup owner draws."))
    raw_manifest, owner = [], []
    count = protocol["owner_worlds_per_profile"]
    for profile, (primary, reference, threshold) in enumerate(profiles):
        outcomes = {arm: [] for arm in protocol["owner_arms"]}
        for begin in range(0, count, 128):
            raw = []
            for world in range(begin, min(begin + 128, count)):
                seed = protocol["owner_seed_namespace"] + profile * 100000 + world
                initial = INITIAL[world % len(INITIAL)]
                for arm, solution, policy, selected in (
                        ("jump_fd", primary, "free", None), ("positive_reference", reference, "free", None),
                        ("mode_fixed_selected", primary, "fixed_mode", threshold), ("stop_now", primary, "stop_now", None)):
                    result = execute(solution, seed, initial, policy, selected)
                    result.update(arm=arm, sigma=primary["config"]["sigma"], world=world)
                    if result["elapsed_steps"] + result["remaining_steps"] != len(primary["times"]) - 1:
                        raise RuntimeError("Owner discarded recovery remaining time")
                    outcomes[arm].append(result)
                    raw.append(result)
            data = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in raw).encode()
            packed = io.BytesIO()
            with gzip.GzipFile(filename="", mode="wb", fileobj=packed, mtime=0, compresslevel=9) as stream:
                stream.write(data)
            compressed = packed.getvalue()
            path = output / f"owner_profile{profile}_part{begin // 128:03d}.jsonl.gz"
            if len(compressed) > 512000:
                raise RuntimeError("Raw part exceeds publication file bound")
            with path.open("xb") as stream:
                stream.write(compressed)
            raw_manifest.append(dict(path=path.name, rows=len(raw), raw_sha256=hashlib.sha256(data).hexdigest(),
                raw_bytes=len(data), sha256=hashlib.sha256(compressed).hexdigest(), bytes=len(compressed)))
        arms = {arm: {f"mean_{metric}": float(np.mean([row[metric] for row in rows])) for metric in
            ("utility", "propensity_utility", "success", "fee")} for arm, rows in outcomes.items()}
        comparisons = {arm: {metric: interval([a[metric] - b[metric] for a, b in zip(outcomes["jump_fd"], outcomes[arm])])
            for metric in ("utility", "propensity_utility")} for arm in ("positive_reference", "mode_fixed_selected", "stop_now")}
        owner.append(dict(sigma=primary["config"]["sigma"], arms=arms, comparisons=comparisons, selected_fixed=threshold))
    finest = [profile["levels"][-1] for profile in numerical]
    smooth = [boundary for row in finest for boundary in row["boundaries"] if "reset_contact" in boundary]
    gate = protocol["gates"]
    gates = dict(lcp_residual=max(r["lcp_residual"] for r in finest) < gate["lcp_residual"],
        finest_reference_value_gap=max(r["primary_reference_max_gap"] for r in finest) < gate["finest_reference_value_gap"],
        finest_consecutive_mesh_gap=max(r["consecutive_mesh_gap"] for r in finest) < gate["finest_consecutive_mesh_gap"],
        refinement_reduces_reference_gap=all(p["levels"][-1]["primary_reference_max_gap"] < p["levels"][0]["primary_reference_max_gap"] for p in numerical),
        finest_smooth_fit_error=bool(smooth) and max(max(r["reset_smooth_fit_error"], r["stop_smooth_fit_error"]) for r in smooth) < gate["finest_smooth_fit_error"],
        contact_value_error=bool(smooth) and max(max(r["reset_value_match"], r["stop_value_match"]) for r in smooth) < gate["contact_value_error"],
        positive_kernel=all(r["minimum_kernel_weight"] >= 0 for p in numerical for r in p["levels"]),
        kernel_mass=max(r["kernel_mass_error"] for p in numerical for r in p["levels"]) < gate["kernel_mass_error"],
        quadrature=max(r["quadrature_difference"] for p in numerical for r in p["levels"]) < gate["quadrature_weight_difference"],
        jump_condition=max(j["jump_condition_error"] for r in finest for j in r["jump_records"]) < gate["jump_condition_error"],
        cosine_consistency=max(r["cosine_consistency_error"] for r in finest) < gate["finest_cosine_consistency_error"])
    result = dict(schema="hcsn-r18-positive-jump-followup-results-v1", source_freeze=freeze,
        classification=protocol["classification"], gates=gates, numerical=numerical, owner=owner,
        model_selection=selections, raw_manifest=raw_manifest, original_run_preserved="run_01/RESULTS.json",
        cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        production_activation=False)
    save(output / "RESULTS.json", result)
    print(json.dumps(dict(gates=gates, owner=owner, cpu_seconds=result["cpu_seconds"]), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
