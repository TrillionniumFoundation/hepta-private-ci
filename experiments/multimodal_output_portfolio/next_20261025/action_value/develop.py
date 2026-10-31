"""Two registered capacities, only original fit and selection sources."""

import argparse
import json
from pathlib import Path
import time

import torch

from ...abc_next.value import features, load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.control import PLANS
from ...closure_20261025.control.development import ce
from .model import CONFIG, GAMMA, ACTION_COST, examples, fit, save


HERE = Path(__file__).resolve().parent


@torch.inference_mode()
def choose_paths(policy, public):
    first = policy.choose(public[:, 0], 2)
    path = torch.zeros(len(first), dtype=torch.long)
    second = torch.full_like(first, -1)
    for action in range(1, 5):
        ids = torch.nonzero(first == action).flatten()
        if len(ids):
            follow = policy.choose(public[ids, action], 1)
            second[ids] = follow
            path[ids] = torch.where(follow == 0, action, 5 + (action - 1) * 4 + follow - 1)
    return path, first, second


def outcome(data, path):
    ids = torch.arange(len(path))
    utility = data["metrics"]["primary"]["utility"][ids, path]
    success = data["metrics"]["primary"]["joint_fact_correct"][ids, path]
    lengths = torch.tensor([len(PLANS[int(p)]) for p in path])
    return {"raw_CE": ce(utility), "action_cost_CE": ce(utility - ACTION_COST * lengths),
            "success": float(success.mean()), "mean_continuation_actions": float(lengths.float().mean())}


@torch.inference_mode()
def diagnostics(policy, data, teacher):
    public, utility = data["features"], data["metrics"]["primary"]["utility"]
    x, target, actual_moments = examples(public, utility)
    predicted = policy.one(x)
    old_moments = teacher.one(features(x, teacher.mode))
    old_delta = old_moments[:, 1:] - old_moments[:, :1]
    feasible = torch.tensor([1, 2, 3])
    paths, first, second = choose_paths(policy, public)
    ids = torch.nonzero(first != 0).flatten()
    selected_public = public[ids, first[ids]]
    prediction = policy.predict(selected_public, 1)[torch.arange(len(ids)), second[ids]]
    deltas = actual_moments[ids, first[ids], second[ids]] - actual_moments[ids, first[ids], 0]
    keep = second[ids] != 0
    bins = []
    for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.)):
        mask = (prediction >= lo) & (prediction < hi) & keep
        bins.append({"range": [lo, hi], "n": int(mask.sum()), "prediction": float(prediction[mask].mean()) if mask.any() else None,
                     "actual": float(deltas[mask].mean()) if mask.any() else None})
    h2_prediction = policy.predict(public[:, 0], 2)[torch.arange(len(public)), first]
    lengths = torch.tensor([len(PLANS[int(p)]) for p in paths])
    h2_actual = torch.exp(-GAMMA * (utility[torch.arange(len(public)), paths] - ACTION_COST * lengths)) - torch.exp(-GAMMA * utility[:, 0])
    return {"feasible_H1_action_difference_MSE": float((predicted[:, feasible] - target[:, feasible]).square().mean()),
        "zero_difference_MSE": float(target[:, feasible].square().mean()),
        "old_teacher_difference_MSE_on_same_public_nodes": float((old_delta[:, feasible] - target[:, feasible]).square().mean()),
        "selected_H1_count": len(ids), "nonstop_H1_count": int(keep.sum()),
        "selected_H1_prediction_bias": float((prediction - deltas).mean()) if len(ids) else None,
        "nonstop_H1_prediction_bias": float((prediction[keep] - deltas[keep]).mean()) if keep.any() else None,
        "nonstop_H1_actual_moment_difference": float(deltas[keep].mean()) if keep.any() else None,
        "nonstop_H1_bins": bins, "selected_H2_prediction_bias": float((h2_prediction - h2_actual).mean()),
        "scope": "Historical selection diagnostics only; actual paired samples, not conditional-optimal labels or a uniform calibration certificate"}


def run(asset, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    historical_path = HERE.parents[1] / "abc_followup/control/DEVELOPMENT.json"
    old = {r["seed"]: r for r in json.loads(historical_path.read_text())["controllers"]}
    source_pins = {str(p.resolve()): file_sha(p) for p in HERE.glob("*.py")}
    inputs = {}
    for seed in (17, 29, 43):
        for name in ("fit", "selection"):
            path = asset / f"abc4-control-runs/development-001/seed-{seed}/{name}/data.pt"
            if file_sha(path) != old[seed][name + "_data_sha256"]: raise ValueError("Original outcome table changed")
            inputs[str(path)] = file_sha(path)
        path = asset / f"abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt"
        if file_sha(path) != old[seed]["old_controller_sha256"]: raise ValueError("Original strong teacher changed")
        inputs[str(path)] = file_sha(path)
    registration = {"schema": "hepta.next.rich-value-development.v1", "started_unix_ns": time.time_ns(),
        "source_sha256": source_pins, "input_sha256": inputs, "seeds": [17, 29, 43], "config": CONFIG,
        "fit_scope": "Only original forecast_fit[480,736), selection forecast_calibration[448,576)",
        "selection": "Choose maximum action-cost CE among candidates with no raw CE or exact-success point loss versus frozen teacher; if none qualifies, keep maximum action-cost CE as an explicitly unadmitted research candidate. No further search.",
        "fresh_outputs_opened": False}
    write_json(output / "registration.json", registration)
    records = []
    for seed in (17, 29, 43):
        started, used = time.perf_counter_ns(), time.process_time_ns()
        folder = asset / f"abc4-control-runs/development-001/seed-{seed}"
        data = torch.load(folder / "fit/data.pt", map_location="cpu", weights_only=True)
        if (data["role"], data["pair_start"], data["pair_count"]) != ("forecast_fit", 480, 256):
            raise ValueError("Invalid historical fitting role")
        teacher = load_controller(asset / f"abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt")
        cases = torch.tensor(data["cases"])
        trained = []
        for width in CONFIG["widths"]:
            policy, fit_report = fit(data["features"], data["metrics"]["primary"]["utility"], cases, width, 2026102600 + seed * 100,
                                     output / f"seed-{seed}-width-{width}-audit")
            destination = output / f"seed-{seed}-width-{width}.pt"
            save(policy, destination)
            trained.append((policy, fit_report, destination))
        del data
        selection = torch.load(folder / "selection/data.pt", map_location="cpu", weights_only=True)
        if (selection["role"], selection["pair_start"], selection["pair_count"]) != ("forecast_calibration", 448, 128):
            raise ValueError("Invalid historical selection role")
        baseline = outcome(selection, teacher.paths(selection["features"]))
        candidates = []
        for policy, report, path in trained:
            value = outcome(selection, choose_paths(policy, selection["features"])[0])
            eligible = value["raw_CE"] >= baseline["raw_CE"] and value["success"] >= baseline["success"]
            candidates.append({"width": report["width"], "fit": report, "checkpoint": str(path), "checkpoint_sha256": file_sha(path),
                "selection_outcome": value, "eligible_for_development_admission": eligible,
                "diagnostics": diagnostics(policy, selection, teacher)})
        admitted = [i for i, c in enumerate(candidates) if c["eligible_for_development_admission"]]
        eligible_indices = admitted or list(range(len(candidates)))
        selected = max(eligible_indices, key=lambda i: (candidates[i]["selection_outcome"]["action_cost_CE"], -i))
        record = {"seed": seed, "teacher": baseline, "candidates": candidates, "selected_index": selected,
                  "selected_width": candidates[selected]["width"], "development_admitted": bool(admitted),
                  "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - used}
        write_json(output / f"seed-{seed}.json", record); records.append(record)
        print(json.dumps({"seed": seed, "selected_width": record["selected_width"], "admitted": bool(admitted),
                          "teacher": baseline, "candidates": [{"width": c["width"], "outcome": c["selection_outcome"], "diagnostics": c["diagnostics"]} for c in candidates]}), flush=True)
        del trained, selection, teacher
    if any(file_sha(Path(p)) != digest for p, digest in source_pins.items()): raise ValueError("Fitting implementation changed during execution")
    write_json(output / "result.json", {"status": "completed", "records": records, "config": CONFIG,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "input_sha256": inputs, "source_sha256": source_pins, "fresh_source_outcomes_used": False,
        "completed_unix_ns": time.time_ns()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.output)
