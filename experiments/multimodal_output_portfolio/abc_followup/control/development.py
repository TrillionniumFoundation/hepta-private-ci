"""Fit cheap conditional state and choose it only on historical development."""

import argparse
import json
from pathlib import Path
import time

import torch

from ...abc_next.compact_tree import collect
from ...abc_next.sensor_run import load_sensor
from ...abc_next.settings import CACHE, FIXED_PLAN, MANIFEST, RUNS, SEEDS, SENSOR, model_path, observers
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.control import PLANS
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .value import CONFIG, fit, save


SELECTION = {"minimum_CE_difference_from_old_feedback": -.002,
             "minimum_success_difference_from_old_feedback": -.005,
             "fallback": "exact_cached_old_feedback",
             "rule": "select compact if both point constraints pass on historical forecast_calibration; otherwise exact cache",
             "risk": "gamma2 and .002 per non-stop action, retained only as development objective, not actual time valuation"}


def evaluate(data, paths):
    metric = data["metrics"]["primary"]
    row = torch.arange(len(paths))
    utility = metric["utility"][row, paths].double()
    success = metric["joint_fact_correct"][row, paths].double()
    lengths = torch.tensor([len(PLANS[p]) for p in paths.tolist()], dtype=torch.float64)
    return {"raw_CE": float(-torch.log(torch.exp(-2 * utility).mean()) / 2),
            "proxy_net_CE": float(-torch.log(torch.exp(-2 * (utility - .002 * lengths)).mean()) / 2),
            "success": float(success.mean()), "mean_actions": float(lengths.mean()),
            "paths": {str(p): int((paths == p).sum()) for p in range(len(PLANS)) if (paths == p).any()}}


def run(output, seeds):
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    write_json(output / "registration.json", {"schema": "hepta.abc4.control-development.v1",
        "started_unix_ns": time.time_ns(), "training_seeds": seeds, "config": CONFIG, "selection": SELECTION,
        "source_role_policy": "Previously accessed forecast_fit[480,736) and forecast_calibration[448,576) only; historical data explicitly reused as development",
        "new_final_outcomes_opened": False})
    corpus = load_roles(CACHE, MANIFEST, roles=("forecast_fit", "forecast_calibration"))
    sensor = load_sensor(SENSOR)
    judges = observers(); primary = {"primary": judges["primary"]}
    historical = json.loads((RUNS / "controllers-001/result.json").read_text())
    references = {e["seed"]: e for e in historical["controllers"] if e["arm"] == "output_ndu"}
    results = []
    for seed in seeds:
        directory = output / f"seed-{seed}"; directory.mkdir()
        snapshot = Snapshot.load(model_path(seed, "output_ndu"))
        old_path = RUNS / f"controllers-001/seed-{seed}/output_ndu/controller.pt"
        old = load_controller(old_path)
        fit_data = collect(snapshot, sensor, corpus, primary, directory / "fit", role="forecast_fit", start=480, count=256, scenarios=2, training_seed=seed)
        candidate = fit(fit_data, 2026102500 + seed)
        save(candidate, directory / "compact.pt")
        del fit_data
        selection = collect(snapshot, sensor, corpus, primary, directory / "selection", role="forecast_calibration", start=448, count=128, scenarios=2, training_seed=seed)
        compact = evaluate(selection, candidate.paths(selection["features"]))
        feedback = evaluate(selection, old.paths(selection["features"]))
        paths = torch.full((len(selection["cases"]),), PLANS.index(FIXED_PLAN), dtype=torch.long)
        fixed = evaluate(selection, paths)
        static_index = references[seed]["selection"]["static_plan_index"]
        static = evaluate(selection, torch.full_like(paths, static_index))
        one_shot = evaluate(selection, old.choose_plan(selection["features"][:, 0]))
        ref_names = ("fixed", "static", "one_shot")
        ref_values = (fixed, static, one_shot)
        best = max(range(3), key=lambda i: (ref_values[i]["proxy_net_CE"], -i))
        conditions = {"CE": compact["proxy_net_CE"] - feedback["proxy_net_CE"] >= SELECTION["minimum_CE_difference_from_old_feedback"],
                      "success": compact["success"] - feedback["success"] >= SELECTION["minimum_success_difference_from_old_feedback"]}
        result = {"seed": seed, "model_sha256": snapshot.fingerprint, "compact_file": str(directory / "compact.pt"),
            "compact_file_sha256": file_sha(directory / "compact.pt"), "old_controller_sha256": file_sha(old_path),
            "fit": candidate.report, "selection": {"compact": compact, "old_feedback": feedback, "fixed": fixed,
                "static": static, "one_shot": one_shot, "compact_constraints": conditions,
                "selected_candidate": "compact" if all(conditions.values()) else "cached",
                "selected_nonfeedback": ref_names[best], "static_plan_index": static_index},
            "fit_data_sha256": file_sha(directory / "fit/data.pt"),
            "selection_data_sha256": file_sha(directory / "selection/data.pt")}
        write_json(directory / "result.json", result); results.append(result)
        print(json.dumps({"phase": "development_complete", "seed": seed, "selected": result["selection"]["selected_candidate"],
                          "compact": compact, "feedback": feedback, "nonfeedback": ref_names[best]}), flush=True)
        del selection, candidate, snapshot
    write_json(output / "result.json", {"schema": "hepta.abc4.control-development-result.v1", "status": "completed",
        "registration_sha256": file_sha(output / "registration.json"), "controllers": results,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "new_generator_training": False, "new_final_outcomes_opened": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    args = parser.parse_args(); run(args.output, args.seeds)
