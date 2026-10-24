"""Registered small forecast/control pilot. Never opens formal holdout roles."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..v6.neural import PROFILES
from .evaluation import load_reward
from .forecast import CategoricalForecast
from .forecast_data import collect_scenarios
from .forecast_fit import catalogue_statistics, family_diagnostic, fit_forecast
from .mechanism import analyze
from .metric import text_image_labeler
from .plans import ControlledSnapshot
from .sources import canonical, load_roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base-run", required=True)
    parser.add_argument("--plan-run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    module = Path(__file__).resolve().parent
    spec = json.loads((module / "forecast_spec.json").read_text())
    sources = [*(module / f"{name}.py" for name in ("sources", "data", "model", "snapshot", "plans", "metric",
                "evaluation", "forecast", "forecast_data", "forecast_fit", "forecast_development", "mechanism", "control")),
               module / "forecast_spec.json",
               *(module.parent / "v6" / f"{name}.py" for name in ("data", "neural", "observer", "plan_training"))]
    pins = {str(path.relative_to(module.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    base_run, plan_run = Path(args.base_run), Path(args.plan_run)
    plan_status = json.loads((plan_run / "status.json").read_text())
    if plan_status.get("status") != "completed" or plan_status.get("formal_holdout_opened"):
        raise ValueError("Forecast pilot requires completed development-only checkpoints")
    reward_report = json.loads((base_run / "reward-observer.json").read_text())
    observer, observer_record = load_reward(base_run / "reward-observer.pt", reward_report["file_sha256"])
    labeler = text_image_labeler(observer, observer_file_sha256=reward_report["file_sha256"])
    corpus = load_roles(args.cache, args.manifest, ("forecast_fit", "forecast_calibration", "development"))
    if (corpus.manifest["manifest_sha256"] != plan_status["source_manifest_sha256"]
            or corpus.manifest["manifest_sha256"] != observer_record["source_manifest_sha256"]):
        raise ValueError("Forecast source/model/reward registration mismatch")
    stamp = {"schema": "hepta.ndu-v7.continuation-pilot.v1", "formal_holdout_opened": False,
             "audit_b_access": False, "source_manifest_sha256": corpus.manifest["manifest_sha256"],
             "source_sha256": pins, "specification": spec,
             "plan_status_file_sha256": hashlib.sha256((plan_run / "status.json").read_bytes()).hexdigest()}
    (output / "status.json").write_bytes(canonical({**stamp, "status": "running"}) + b"\n")
    torch.set_num_threads(spec["threads"])
    started, results = time.perf_counter_ns(), {}
    for profile in PROFILES:
        current = output / profile
        current.mkdir()
        record = plan_status["result"][profile]
        snapshot = ControlledSnapshot.load(plan_run / f"{profile}.pt", expected_file_sha256=record["file_sha256"])
        datasets = {}
        for name, role in (("fit", "forecast_fit"), ("calibration", "forecast_calibration"), ("development", "development")):
            print(json.dumps({"profile": profile, "stage": f"collect_{name}"}), flush=True)
            datasets[name] = collect_scenarios(snapshot, corpus, role, labeler, spec[f"{name}_pairs"],
                                                current / name, scenarios=spec[f"{name}_latent_scenarios"])
        print(json.dumps({"profile": profile, "stage": "fit_source_group_oof"}), flush=True)
        artifact, evidence = fit_forecast(snapshot, datasets["fit"], datasets["calibration"], labeler.contract,
                                          seed=spec["training_seed"], steps=spec["steps_per_fit"],
                                          folds=spec["source_pair_oof_folds"], batch_size=spec["fit_batch_size"],
                                          alpha=spec["finite_family_calibration_alpha"])
        sha = artifact.save(current / "forecast.pt")
        restored = CategoricalForecast.load(current / "forecast.pt", expected_file_sha256=sha)
        statistics = catalogue_statistics(restored._head, datasets["development"], temperature=restored.temperature)
        development = family_diagnostic(statistics, datasets["development"], radius=restored.calibration["radius"])
        mechanism = analyze(datasets["development"], statistics,
                             gammas=tuple(spec["development_gamma_diagnostic"]),
                             penalty=spec["continuation_action_penalty"])
        (current / "fit-evidence.json").write_bytes(canonical(evidence) + b"\n")
        (current / "development-diagnostic.json").write_bytes(canonical(development) + b"\n")
        (current / "mechanism.json").write_bytes(canonical(mechanism) + b"\n")
        results[profile] = {"forecast_file_sha256": sha, "forecast_fingerprint": restored.fingerprint,
                            "snapshot_sha256": snapshot.fingerprint, "temperature": restored.temperature,
                            "calibration_radius": restored.calibration["radius"],
                            "development_mae": development["source_balanced_mae"],
                            "development_crps": development["source_balanced_crps"],
                            "development_central90_coverage": development["source_balanced_central90_coverage"],
                            "finite_family_all_covered_fraction": development["finite_family_all_covered_fraction"],
                            "finite_family_mean_width": development["source_balanced_finite_family_width"],
                            "policy_outcomes": {name: {key: value for key, value in outcome.items()
                                                      if key != "selected_endpoint_indices"}
                                                 for name, outcome in mechanism["policy_outcomes"].items()},
                            "risk_neutral_vs_gamma2": mechanism["risk_neutral_vs_gamma2"],
                            "common_noise_precommitted_plan_oracle": mechanism["common_noise_precommitted_plan_oracle"]}
        print(json.dumps({"profile": profile, **results[profile]}, sort_keys=True), flush=True)
        del datasets, statistics
    if pins != {str(path.relative_to(module.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("Forecast pilot execution source changed")
    completed = {**stamp, "status": "completed", "wall_ns": time.perf_counter_ns() - started,
                 "result": results, "global_scientific_success": False}
    (output / "status.json").write_bytes(canonical(completed) + b"\n")
    print(json.dumps(completed, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
