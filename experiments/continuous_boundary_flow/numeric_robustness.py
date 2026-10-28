"""Postconfirmation numerical diagnostics only; no training, sampling or new gates.
Read completed evidence to compare refined grids and an independent CTMC reference; do not replace frozen results.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time

CONFIGS = [("analytic64_4.8", 64, 4.8), ("analytic128_4.8", 128, 4.8), ("analytic192_7.2", 192, 7.2), ("fd240_7.2", 240, 7.2)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), "Invalid evidence path")
    return path


def timed(function):
    cpu, wall = time.process_time(), time.perf_counter()
    result = function()
    return result, {"cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall}


def difference(a, b):
    pairs = list(zip(a["boundaries"], b["boundaries"], strict=True))
    delta = [None if x is None or y is None else x - y for x, y in pairs]
    return {
        "initial_value_difference": a["initial_value"] - b["initial_value"],
        "boundary_differences_remaining_1_to_N": delta,
        "max_abs_boundary_difference": max((abs(x) for x in delta if x is not None), default=None),
        "undefined_boundary_pairs": sum(x is None for x in delta),
    }


def numeric(scenario):
    from .math_model import TaskSpec, build_model, evaluate_policy, solve_dp
    from .oracle import finite_difference_reference

    spec, outputs = TaskSpec(**scenario["spec"]), {}
    for name, grid, domain in CONFIGS:
        if name.startswith("analytic"):
            model, build_cost = timed(lambda: build_model(spec, n_grid=grid, x_max=domain))
            solution, solve_cost = timed(lambda: solve_dp(model))
            row = {
                "initial_value": solution["initial_value"],
                "boundaries": [x["boundary"] for x in solution["boundaries"]],
                "boundary_details": solution["boundaries"],
                "model_diagnostics": model.diagnostics,
                "cost": {"model_build": build_cost, "dp_solve": solve_cost},
            }
            if grid == 64:
                flow, flow_cost = timed(lambda: evaluate_policy(model, solution["policy"]))
                fields = ("utility", "upper_tail_visits", "mass_error", "flow_backward_residual", "stopped_probability")
                row["policy_flow"] = {key: flow[key] for key in fields}
                row["policy_flow"]["utility_minus_dp_initial"] = flow["utility"] - solution["initial_value"]
                row["policy_flow"]["expected_pre_action_visits"] = {
                    str(x): float(flow["occupancy"][:-1, model.x >= x].sum()) for x in (3.6, 4.5)
                }
                row["cost"]["policy_evaluation"] = flow_cost
        else:
            solution, cost = timed(lambda: finite_difference_reference(spec, n_grid=grid, x_max=domain))
            fields = ("initial_value", "boundaries", "method", "mass_error", "min_transition", "dx")
            row = {key: solution[key] for key in fields}
            row["cost"] = {"independent_build_and_dp": cost}
        outputs[name] = row
    baseline = outputs["analytic64_4.8"]
    saved = {"initial_value": scenario["dp_initial_value"], "boundaries": [x["boundary"] for x in scenario["boundaries"]]}
    reproduction = difference(baseline, saved)
    require(abs(reproduction["initial_value_difference"]) < 1e-10, "Default DP initial value changed")
    require(
        all(
            a == b if a is None or b is None else abs(a - b) < 1e-10
            for a, b in zip(baseline["boundaries"], saved["boundaries"], strict=True)
        ),
        "Default DP boundaries changed",
    )
    return {
        "context_id": scenario["id"],
        "split": scenario["id"].split(".")[1],
        "spec": scenario["spec"],
        "grids": outputs,
        "default_reproduction": reproduction,
        "versus_default": {name: difference(row, baseline) for name, row in outputs.items() if row is not baseline},
        "same_dx_domain_change": difference(outputs["analytic192_7.2"], outputs["analytic128_4.8"]),
        "independent_reference_minus_wide_analytic": difference(outputs["fd240_7.2"], outputs["analytic192_7.2"]),
    }


def occupancy(root, manifest, scenarios, protocol):
    specs, seen, total = {r["id"]: r["spec"] for r in scenarios}, set(), 0
    keys = ("episodes", "decision_visits", "x_ge_3.6", "x_ge_4.5", "last_bin_visits", "max_recorded_x")
    accum = {
        (arm, split): dict(arm=arm, split=split, **dict.fromkeys(keys, 0))
        for arm in manifest["arms"]
        for split in manifest["splits"]
    }
    for entry in manifest["records"]:
        path = contained(root, entry["path"])
        require(digest(path) == entry["sha256"], "Raw compressed digest mismatch")
        uncompressed, size, count = hashlib.sha256(), 0, 0
        with gzip.open(path, "rb") as stream:
            for line in stream:
                uncompressed.update(line)
                size, count = size + len(line), count + 1
                record = json.loads(line)
                prefix, index = record["episode_id"].rsplit(".p", 1)[0].rsplit(".c", 1)
                context_id = f"{prefix}.context{index}"
                require(
                    prefix == f"{record['train_seed']}.{record['split']}" and specs.get(context_id) == record["spec"],
                    "Raw episode/context mismatch",
                )
                key = (record["arm"], record["episode_id"])
                require(key not in seen, "Duplicate raw episode")
                seen.add(key)
                acc = accum[(record["arm"], record["split"])]
                acc["episodes"] += 1
                for step in record["steps"]:
                    x = step["x"]
                    require(math.isfinite(x) and 0 < x < 4.8, "Invalid frozen-grid state")
                    acc["decision_visits"] += 1
                    acc["max_recorded_x"] = max(acc["max_recorded_x"], x)
                    acc["last_bin_visits"] += step["state_idx"] == 63
                    for threshold in (3.6, 4.5):
                        acc[f"x_ge_{threshold}"] += x >= threshold
        require(
            count == entry["count"]
            and size == entry["uncompressed_bytes"]
            and uncompressed.hexdigest() == entry["uncompressed_sha256"],
            "Raw expanded digest/count mismatch",
        )
        total += count
    expected = {
        (arm, f"{r['id'].replace('.context', '.c')}.p{i}")
        for arm in manifest["arms"]
        for r in scenarios
        for i in range(protocol["confirmation_episodes_per_context"])
    }
    require(seen == expected, "Raw confirmation coverage mismatch")
    for acc in accum.values():
        for key in ("x_ge_3.6", "x_ge_4.5", "last_bin_visits"):
            acc[key + "_fraction"] = acc[key] / acc["decision_visits"] if acc["decision_visits"] else None
    return {
        "episodes": total,
        "by_arm_split": list(accum.values()),
        "scope": "Pooled pre-action decision visits, including terminal stop decisions; stopped later windows absent. "
        "Recorded grid-bin centers do not identify actual continuous path maxima or within-window excursions.",
    }


def run(root, output):
    cpu, wall = time.process_time(), time.perf_counter()
    require(not output.exists() and not output.resolve().is_relative_to(root), "Output must be new and outside frozen study")
    manifest_path, scenario_path = root / "manifest.json", root / "SCENARIOS.json"
    manifest, scenarios = json.loads(manifest_path.read_text()), json.loads(scenario_path.read_text())
    protocol_path, seal_path = root / "protocol.json", root / "SOURCE_SEAL.json"
    protocol, seal = json.loads(protocol_path.read_text()), json.loads(seal_path.read_text())
    require(
        digest(protocol_path) == manifest["protocol_sha256"] and digest(seal_path) == manifest["source_seal_sha256"],
        "Frozen protocol/source seal mismatch",
    )
    require(
        len(scenarios) == 128
        and len({r["id"] for r in scenarios}) == 128
        and {r["id"] for r in scenarios} == set(protocol["phase_ids"]["confirmation"]),
        "Expected fixed 128 contexts",
    )
    require(manifest["grid_states"] == 64 and manifest["grid_upper_domain"] == 4.8, "Unexpected frozen grid")
    package = Path(__file__).resolve().parent
    source_hashes = {}
    for name in ("math_model.py", "oracle.py", "../first_passage_cell/kernels.py"):
        path = (package / name).resolve()
        relative = str(path.relative_to(package.parent.parent))
        source_hashes[relative] = digest(path)
        require(seal["source_files"].get(relative) == source_hashes[relative], "Immutable math source changed")
    import numpy as np
    import scipy

    rows, numeric_cost = timed(lambda: [numeric(scenario) for scenario in scenarios])
    observed, raw_cost = timed(lambda: occupancy(root, manifest, scenarios, protocol))
    phase_costs = {}
    for row in rows:
        for config, result in row["grids"].items():
            for phase, cost in result["cost"].items():
                acc = phase_costs.setdefault(config + ":" + phase, {"cpu_seconds": 0.0, "wall_seconds": 0.0})
                for key, value in cost.items():
                    acc[key] += value
    source = Path(__file__).read_bytes()
    report = {
        "schema": "hepta.continuous-boundary.postconfirmation-numeric-robustness.v1",
        "scope": "Postconfirmation descriptive numerical limitation checks only; no new samples, training, selection or primary gates.",
        "inputs": {
            "files": {p.name: digest(p) for p in (manifest_path, scenario_path, protocol_path, seal_path)},
            "math_source_sha256": source_hashes,
        },
        "executed_source_sha256": hashlib.sha256(source).hexdigest(),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "configurations": CONFIGS,
        "contexts": rows,
        "raw_occupancy": observed,
        "cost": {
            "numerical_all_inclusive": numeric_cost,
            "numerical_included_subtimers": phase_costs,
            "raw_hashing_and_occupancy": raw_cost,
            "whole_analysis_cpu_seconds": time.process_time() - cpu,
            "whole_analysis_wall_seconds": time.perf_counter() - wall,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "scope": "Separate postconfirmation CPU; no child processes; whole-analysis excludes final JSON write. Subtimers overlap totals.",
        },
        "limitations": [
            "All grids approximate the same finite-window task; this is not a continuous-time smooth-pasting solution.",
            "Analytic128/4.8 and analytic192/7.2 share dx=0.0375; FD240/7.2 has dx=7.2/241 and a reflecting upper edge.",
            "Analytic overflow is collapsed into the final bin. upper_tail_visits sums expected surviving endpoint mass above the domain; it is not an excursion probability.",
            "Small mass error tests conservation, not domain accuracy. These comparisons do not establish an infinite-domain error bound.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "NUMERIC_ROBUSTNESS.json").open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--confirmation-complete", action="store_true", required=True)
    args = parser.parse_args()
    report = run(args.study_dir.resolve(), args.output_dir.resolve())
    print(json.dumps({"contexts": len(report["contexts"]), "cost": report["cost"]}, sort_keys=True))


if __name__ == "__main__":
    main()
