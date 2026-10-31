"""Matched representation/capacity development before a separately sealed test."""

import argparse
import json
from pathlib import Path
import time

import torch

from ..abc_recovery.base_recovery import file_sha, write_json
from ..abc_recovery.control import PLANS
from ..abc_recovery.risk import conditional_ce
from ..v7.snapshot import Snapshot
from ..v7.sources import load_roles
from .compact_tree import collect
from .sensor_run import load_sensor
from .settings import (ARMS, CACHE, FIXED_PLAN, MANIFEST, RUNS, SEEDS, SENSOR, SOURCE_RANGES,
                       model_path, observers, resources, source_pins)
from .value import CANDIDATES, CONFIG, fit_controller, load_controller, save_controller


def evaluate(controller, data):
    with torch.inference_mode():
        paths = {"feedback": controller.paths(data["features"]),
                 "one_shot": controller.choose_plan(data["features"][:, 0]),
                 "fixed": torch.full((len(data["cases"]),), PLANS.index(FIXED_PLAN))}
    utility = data["metrics"]["primary"]["utility"].double()
    lengths = torch.tensor([len(p) for p in PLANS])
    ce = [conditional_ce((utility[:, i] - .002 * lengths[i]).tolist(), gamma=2.) for i in range(21)]
    static = max(range(21), key=ce.__getitem__)
    paths["static"] = torch.full((len(utility),), static)
    metrics = {}
    rows = torch.arange(len(utility))
    for name, selected in paths.items():
        u = utility[rows, selected] - .002 * lengths[selected]
        metrics[name] = {"net_joint_CE": conditional_ce(u.tolist(), gamma=2.),
                         "joint_success": float(data["metrics"]["primary"]["joint_fact_correct"][rows, selected].mean()),
                         "mean_actions": float(lengths[selected].float().mean()),
                         "plan_counts": torch.bincount(selected, minlength=21).tolist()}
    nonfeedback = max(("fixed", "static", "one_shot"), key=lambda p: metrics[p]["net_joint_CE"])
    return {"metrics": metrics, "static_plan_index": static, "static_all_plan_CE": ce,
            "selected_nonfeedback": nonfeedback,
            "selection_is_optimistic_development_only": True}


def begin(outdir, kind):
    outdir.mkdir(parents=True, exist_ok=False)
    pins, inputs = source_pins(), resources()
    write_json(outdir / "registration.json", {
        "schema": "hepta.abc-next.development-registration.v1", "phase": kind,
        "registered_unix_ns": time.time_ns(), "resources": inputs, "source_sha256": pins,
        "source_ranges": SOURCE_RANGES, "architecture_candidates": CANDIDATES, "fit_config": CONFIG,
        "architecture_selection": "seed17 output_ndu only; highest Primary feedback net joint CE; candidate order breaks ties",
        "H1_semantic_dominance_constraint_all_candidates": True,
        "nonfeedback_selection": "per seed/arm best of fixed, fit-selected static, matched one-shot on selection sources",
        "formal_test_outcomes_opened": False,
        "secondary_scores_used_for_selection": False,
        "newly_trained_generator_weights": False,
        "training_axis": "frozen operational mean versus risk moment, each with unchanged 0.05 auxiliary loss"})
    return pins, inputs


def selection(outdir):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    pins, inputs = begin(outdir, "architecture_selection")
    corpus = load_roles(CACHE, MANIFEST, roles=("forecast_fit", "forecast_calibration"))
    sensor, judges = load_sensor(SENSOR), observers()
    snapshot = Snapshot.load(model_path(17, "output_ndu"), expected_file_sha256=inputs["model_sha256"]["17/output_ndu"])
    fit = collect(snapshot, sensor, corpus, judges, outdir / "fit", training_seed=17, **SOURCE_RANGES["fit"])
    selected = collect(snapshot, sensor, corpus, judges, outdir / "selection", training_seed=17, **SOURCE_RANGES["selection"])
    results = []
    for mode, hidden in CANDIDATES:
        started = time.perf_counter_ns()
        controller = fit_controller(fit, mode, hidden, seed=2026102517)
        name = f"{mode}-{hidden}"
        save_controller(controller, outdir / (name + ".pt"))
        result = {"candidate": name, "mode": mode, "hidden": hidden,
                  "controller_sha256": file_sha(outdir / (name + ".pt")),
                  "selection": evaluate(controller, selected), "fit": controller.report,
                  "fit_and_selection_wall_ns": time.perf_counter_ns() - started}
        write_json(outdir / (name + ".json"), result)
        results.append(result)
        print(json.dumps({"candidate": name, "selection": result["selection"]["metrics"]}), flush=True)
    best = max(range(len(results)), key=lambda i: results[i]["selection"]["metrics"]["feedback"]["net_joint_CE"])
    if pins != source_pins() or inputs != resources():
        raise ValueError("Frozen implementation or resources changed during selection")
    write_json(outdir / "result.json", {
        "schema": "hepta.abc-next.architecture-selection.v1", "status": "completed",
        "registration_sha256": file_sha(outdir / "registration.json"), "candidates": results,
        "selected": {k: results[best][k] for k in ("candidate", "mode", "hidden", "controller_sha256")},
        "formal_test_outcomes_opened": False, "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu})


def fit_all(outdir, selection_dir):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    choice = json.loads((selection_dir / "result.json").read_text())["selected"]
    pins, inputs = begin(outdir, "all_frozen_generator_controllers")
    corpus = load_roles(CACHE, MANIFEST, roles=("forecast_fit", "forecast_calibration"))
    sensor, judges = load_sensor(SENSOR), observers()
    results = []
    for seed in SEEDS:
        for arm in ARMS:
            entry = outdir / f"seed-{seed}" / arm
            entry.mkdir(parents=True)
            if seed == 17 and arm == "output_ndu":
                controller = load_controller(selection_dir / (choice["candidate"] + ".pt"))
                data = torch.load(selection_dir / "selection/data.pt", weights_only=True)
                fit_reference = str(selection_dir / "fit/summary.json")
            else:
                snapshot = Snapshot.load(model_path(seed, arm), expected_file_sha256=inputs["model_sha256"][f"{seed}/{arm}"])
                fit = collect(snapshot, sensor, corpus, judges, entry / "fit", training_seed=seed, **SOURCE_RANGES["fit"])
                controller = fit_controller(fit, choice["mode"], choice["hidden"], seed=2026102500 + seed)
                del fit
                data = collect(snapshot, sensor, corpus, judges, entry / "selection", training_seed=seed, **SOURCE_RANGES["selection"])
                fit_reference = str(entry / "fit/summary.json")
            selected = evaluate(controller, data)
            del data
            save_controller(controller, entry / "controller.pt")
            result = {"seed": seed, "arm": arm, "selection": selected, "fit": controller.report,
                      "controller_file": str(entry / "controller.pt"),
                      "controller_sha256": file_sha(entry / "controller.pt"), "fit_reference": fit_reference,
                      "fit_summary_sha256": file_sha(Path(fit_reference))}
            write_json(entry / "result.json", result)
            results.append(result)
            print(json.dumps({"seed": seed, "arm": arm, "selection": selected["metrics"],
                              "selected_nonfeedback": selected["selected_nonfeedback"]}), flush=True)
    if pins != source_pins() or inputs != resources():
        raise ValueError("Implementation or resources changed during controller fit")
    write_json(outdir / "result.json", {"schema": "hepta.abc-next.controller-freeze.v1", "status": "completed",
        "registration_sha256": file_sha(outdir / "registration.json"), "selection_result_sha256": file_sha(selection_dir / "result.json"),
        "architecture": choice, "controllers": results, "formal_test_outcomes_opened": False,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("selection", "fit-all"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=RUNS / "architecture-001")
    args = parser.parse_args()
    torch.set_num_threads(2)
    try:
        selection(args.output) if args.phase == "selection" else fit_all(args.output, args.selection)
    except BaseException as error:
        if args.output.exists():
            write_json(args.output / "failure.json", {"error": repr(error), "unix_ns": time.time_ns()})
        raise


if __name__ == "__main__":
    main()
