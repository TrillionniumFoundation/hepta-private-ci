#!/usr/bin/env python3
"""Reproducible preregistered pilot; local evidence cannot attest cloud execution."""

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

import numpy as np
import torch

from audit import audit_planner
from control import CalibrationModel, Planner, portfolio_grid
from evaluate import evaluate_rollout, predict_all, select_policies
from metrics import paired_bootstrap, score_outputs, summarize
from model import generate, mac_counts, save_model, train_model
from world import MODALITIES, canonical, render, sample_worlds


HERE = Path(__file__).resolve().parent


def write_json(path, value):
    with path.open("x", encoding="utf-8") as destination:
        json.dump(value, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write("\n")


def source_manifest():
    files = [*HERE.glob("*.py"), HERE / "protocol.json", HERE / "run_cloud.sh"]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(files) if path.exists()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"files": hashes, "combined_sha256": digest}


def runtime_receipt(tier, manifest):
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE,
                               capture_output=True, text=True, check=False)
    return {"execution_tier": tier, "host": socket.gethostname(),
            "platform": platform.platform(), "python": sys.version,
            "python_executable": sys.executable, "numpy": np.__version__,
            "torch": str(torch.__version__), "torch_cuda_available": torch.cuda.is_available(),
            "model_device": "cpu", "cpu_count": os.cpu_count(),
            "git_checkout_head": completed.stdout.strip(),
            "source_commit_asserted_by_launcher": os.environ.get("HEPTA_EXPERIMENT_SOURCE_COMMIT"),
            "source_manifest": manifest, "command": sys.argv,
            "runner_name": os.environ.get("RUNNER_NAME"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "dedicated_runner_verified": tier == "dedicated-cloud",
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def clear_controller_caches():
    for function in (Planner.solve, Planner.stop, Planner.candidates,
                     CalibrationModel.posterior, CalibrationModel.predictive):
        function.cache_clear()


def execute(output, tier, smoke=False):
    protocol = json.loads((HERE / "protocol.json").read_text())
    if tier == "dedicated-cloud" and not (
        os.environ.get("HEPTA_DEDICATED_RUNNER_VERIFIED") == "1"
        and os.environ.get("RUNNER_NAME") == "desktop"
        and os.environ.get("GITHUB_RUN_ID")
    ):
        raise RuntimeError("dedicated cloud execution needs the verified desktop launcher")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "protocol.json", protocol)
    manifest = source_manifest()
    runtime = runtime_receipt(tier, manifest)
    runtime["smoke_only"] = smoke
    write_json(output / "runtime-start.json", runtime)
    started = time.perf_counter()
    progress_path = output / "progress.jsonl"

    def progress(event, **fields):
        row = {"event": event, "elapsed_seconds": time.perf_counter() - started, **fields}
        with progress_path.open("a", encoding="utf-8") as destination:
            destination.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    seeds = [5] if smoke else protocol["seeds"]
    sizes = dict(protocol["splits"])
    if smoke:
        sizes = {key: min(value, 128 if key.startswith("test") else 256)
                 for key, value in sizes.items()}
    steps = 80 if smoke else protocol["train_steps"]
    grid, targets = portfolio_grid(), canonical()
    budgets = protocol["budgets_after_initial_text"]
    summary_rows, training_rows, audit_rows, retained = [], [], [], {}
    per_world_path = output / "per_world.csv.gz"
    columns = ["seed", "scenario", "budget", "arm", "world_id", "truth", "loss",
               "quality", "resolved_correct", "omission", "contradiction", "raw_error",
               "linear_macs", "acquisition_units", "portfolio_index", "portfolio",
               "preference", "public_trace", "scenario_component"]
    with gzip.open(per_world_path, "wt", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        for seed in seeds:
            progress("training_start", seed=seed)
            seed_output = output / f"seed-{seed}"
            seed_output.mkdir()
            labels = np.random.default_rng(seed + 100).integers(8, size=sizes["train"])
            training_raw = render(labels, seed=seed + 1000, nuisance=True)
            model, training = train_model(training_raw, labels, targets, seed, steps=steps)
            training["data_generation"] = {
                "kind": "independent_clean_render_worlds", "label_rng_seed": seed + 100,
                "nuisance_rng_seed": seed + 1000,
                "sample_id_namespace": f"clean-train:{seed}:",
                "raw_sha256": {name: hashlib.sha256(values.tobytes()).hexdigest()
                               for name, values in training_raw.items()},
                "note": "Clean training classes are shared concepts; independent nuisance draws and RNG namespaces separate datasets, not unseen-class generalization."}
            training_rows.append(training)
            save_model(model, seed_output / "model.pt")
            write_json(seed_output / "training.json", training)
            del training_raw
            progress("training_complete", seed=seed, seconds=training["training_wall_seconds"],
                     parameter_groups_changed=training["parameter_groups_changed"])

            calibration = sample_worlds(sizes["calibration"], seed=10000 + seed,
                                        split="calibration", scenario="iid")
            predictions, calibration_cost = predict_all(model, calibration["raw"])
            joint_model = CalibrationModel(calibration["truth"], predictions,
                                           protocol["joint_smoothing_total_count"])
            independent_model = CalibrationModel(calibration["truth"], predictions,
                                                  protocol["joint_smoothing_total_count"], True)
            expected_reports = np.where(calibration["reports"] < 0, 8, calibration["reports"])
            calibration_accuracy = {name: float((predictions[:, j] == expected_reports[:, j]).mean())
                                    for j, name in enumerate(MODALITIES)}
            np.savez_compressed(seed_output / "calibration.npz", joint=joint_model.joint,
                                independent_joint=independent_model.joint,
                                truth=calibration["truth"], predictions=predictions)
            del calibration
            candidate_start = time.perf_counter()
            candidates = generate(model, grid)
            vertices = np.asarray([np.flatnonzero(grid[:, label] == 1)[0] for label in range(8)])
            clean_generation = summarize(score_outputs(
                {name: values[vertices] for name, values in candidates.items()},
                np.arange(8, dtype=np.int64), targets))
            loss_table = np.column_stack([
                score_outputs(candidates, np.full(len(grid), label, dtype=np.int64), targets)["loss"]
                for label in range(8)])
            np.savez_compressed(seed_output / "portfolio_losses.npz", portfolios=grid, losses=loss_table)
            candidate_seconds = time.perf_counter() - candidate_start
            del candidates
            planners = {}
            modes = {"risk_neutral_dp": "neutral", "fixed_risk_dp": "fixed",
                     "ndu_recursive_dp": "ndu", "ndu_myopic": "myopic",
                     "best_single_candidate": "single", "ndu_independent_error_ablation": "ndu"}
            for arm, mode in modes.items():
                gammas = [0.0] if mode == "neutral" else protocol["gamma_grid"]
                risk_model = independent_model if "independent" in arm else joint_model
                planners[arm] = [Planner(risk_model, loss_table, grid, gamma=gamma, mode=mode,
                                         penalty=protocol["cost_penalty"]) for gamma in gammas]
                for planner in planners[arm]:
                    planner.compile(budgets)
            progress("policies_compiled", seed=seed,
                     compile_seconds=sum(p.compile_seconds for ps in planners.values() for p in ps),
                     calibration_encoder_accuracy=calibration_accuracy)
            validation = sample_worlds(sizes["validation"], seed=20000 + seed,
                                       split="validation", scenario="iid")
            validation_predictions, validation_cost = predict_all(model, validation["raw"])
            selection_start = time.perf_counter()
            selections, selection = select_policies(validation_predictions, validation["truth"],
                                                     loss_table, grid, planners, budgets)
            selection_seconds = time.perf_counter() - selection_start
            write_json(seed_output / "validation-selection.json", selection)
            del validation
            audited = set()
            for (budget, arm), planner in selections.items():
                if isinstance(planner, dict) or id(planner) in audited:
                    continue
                audited.add(id(planner))
                misses_before = Planner.solve.cache_info().misses
                result = audit_planner(planner, budgets=budgets, compare_all=True)
                if Planner.solve.cache_info().misses != misses_before:
                    raise AssertionError("independent audit filled unpaid policy states")
                if not result["passed"]:
                    write_json(seed_output / "failed-audit.json", result)
                    raise AssertionError("independent augmented-state oracle disagrees")
                audit_rows.append({"seed": seed, "arm": arm, "gamma": planner.gamma, **result})
            write_json(seed_output / "audit.json", [row for row in audit_rows if row["seed"] == seed])
            costs = {"calibration": calibration_cost, "validation": validation_cost,
                     "calibration_encoder_accuracy": calibration_accuracy,
                     "canonical_generation_evaluation": clean_generation,
                     "candidate_generation_examples": len(grid), "candidate_and_loss_table_seconds": candidate_seconds,
                     "candidate_generation_linear_macs": len(grid) * mac_counts(model)["generate_all_modalities"],
                     "validation_selection_seconds": selection_seconds,
                     "compile_seconds": {arm: [{"gamma": p.gamma, "seconds": p.compile_seconds}
                                               for p in ps] for arm, ps in planners.items()},
                     "note": "Offline training/calibration/compilation and external evaluation are reported separately; Linear MAC is not total physical cost."}
            write_json(seed_output / "offline-costs.json", costs)
            progress("selection_frozen_and_audited", seed=seed,
                     selected_gamma_budget4=selection["4"]["ndu_recursive_dp"]["gamma"])
            for split_index, scenario in enumerate(("test_iid", "correlation_shift", "all_shared_wrong")):
                world = sample_worlds(sizes[scenario], seed=protocol.get("heldout_seed_base", 100000) + 100 * seed + split_index,
                                      split=scenario, scenario="iid" if scenario == "test_iid" else scenario)
                for budget in budgets:
                    for arm in protocol["arms"]:
                        policy = selections[(budget, arm)]
                        misses_before = Planner.solve.cache_info().misses
                        scores, receipt, summary = evaluate_rollout(model, world, policy, budget, grid, targets)
                        if Planner.solve.cache_info().misses != misses_before:
                            raise AssertionError("heldout policy compilation was not completely prepaid")
                        summary_rows.append({"seed": seed, "scenario": scenario, "budget": budget,
                                             "arm": arm, **summary})
                        if scenario == "test_iid" and budget == 4:
                            retained[(seed, arm)] = {"loss": scores["loss"].copy(),
                                                    "quality": scores["quality"].copy(),
                                                    "macs": receipt["linear_macs"].copy()}
                        for i, world_id in enumerate(world["ids"]):
                            portfolio = int(receipt["portfolio_indices"][i])
                            writer.writerow({"seed": seed, "scenario": scenario, "budget": budget,
                                "arm": arm, "world_id": world_id, "truth": int(world["truth"][i]),
                                "loss": float(scores["loss"][i]), "quality": float(scores["quality"][i]),
                                "resolved_correct": float(scores["resolved_correct_fraction"][i]),
                                "omission": float(scores["omission"][i]),
                                "contradiction": float(scores["contradiction"][i]),
                                "raw_error": float(scores["raw_error"][i]),
                                "linear_macs": int(receipt["linear_macs"][i]),
                                "acquisition_units": int(receipt["acquisition_units"][i]),
                                "portfolio_index": portfolio, "portfolio": json.dumps(grid[portfolio].tolist()),
                                "preference": int(receipt["preference"][i]),
                                "public_trace": json.dumps(receipt["trace"][i]),
                                "scenario_component": str(world["scenario"][i])})
                destination.flush()
                progress("scenario_complete", seed=seed, scenario=scenario, worlds=len(world["truth"]))
                del world
            clear_controller_caches()

    contrasts = {}
    primary_arm = "ndu_recursive_dp"
    for baseline in protocol["arms"]:
        if baseline == primary_arm:
            continue
        left = np.stack([retained[(seed, primary_arm)]["loss"] for seed in seeds])
        right = np.stack([retained[(seed, baseline)]["loss"] for seed in seeds])
        contrasts[baseline] = {metric: paired_bootstrap(left, right, statistic=metric,
                              seed=7891, replicates=1000, shared_worlds=False)
                              for metric in ("mean", "cvar90")}
        quality_delta = np.mean([retained[(seed, primary_arm)]["quality"].mean()
                                 - retained[(seed, baseline)]["quality"].mean() for seed in seeds])
        mean_macs = {arm: float(np.mean([retained[(seed, arm)]["macs"].mean() for seed in seeds]))
                     for arm in (primary_arm, baseline)}
        contrasts[baseline].update({"mean_quality_delta": float(quality_delta),
                                    "mean_linear_mac_ratio": mean_macs[primary_arm] / mean_macs[baseline]})
    primary = contrasts["validation_selected_fixed_portfolio"]
    primary_gates = {"cvar_reduction_at_least_0_02": primary["cvar90"]["estimate"] <= -0.02,
                     "cvar_95pct_interval_below_zero": primary["cvar90"]["ci_high"] < 0,
                     "quality_noninferior_within_0_02": primary["mean_quality_delta"] >= -0.02,
                     "linear_mac_ratio_at_most_1_05": primary["mean_linear_mac_ratio"] <= 1.05,
                     "three_registered_seeds": seeds == protocol["seeds"] and not smoke,
                     "independent_oracle_parity": all(row["passed"] for row in audit_rows),
                     "verified_dedicated_cloud": tier == "dedicated-cloud"}
    source_after = source_manifest()
    if source_after != manifest:
        raise RuntimeError("source changed during the experiment; evidence cannot be frozen")
    report = {"protocol_id": protocol["protocol_id"], "execution_tier": tier,
              "smoke_only": smoke, "seeds": seeds, "rows": summary_rows,
              "primary_budget4_iid_contrasts": contrasts, "primary_gates": primary_gates,
              "primary_claim_passed": all(primary_gates.values()),
              "audit_count": len(audit_rows), "training": training_rows,
              "wall_seconds": time.perf_counter() - started,
              "scope": protocol["scope"], "source_manifest": manifest}
    write_json(output / "summary.json", report)
    write_json(output / "completion.json", {"exit_code": 0, "implementation_run_completed": True,
               "primary_claim_passed": all(primary_gates.values()), "execution_tier": tier,
               "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    progress("complete", primary_gates=primary_gates, primary=primary)
    hashes = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "evidence-manifest.json", hashes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution-tier", choices=("local-preflight", "dedicated-cloud"),
                        default="local-preflight")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; existing evidence must not be modified")
    try:
        execute(args.output.resolve(), args.execution_tier, args.smoke)
    except Exception as error:
        if args.output.exists():
            failure = args.output / f"failure-{time.time_ns()}.json"
            write_json(failure, {"exception": type(error).__name__, "message": str(error),
                                 "exit_code": 1, "execution_tier": args.execution_tier})
        raise


if __name__ == "__main__":
    main()
