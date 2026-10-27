"""Freeze-compatible orchestration for the original two-tick feedback study."""

import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .feedback_chain import build_feedback_dataset, evaluate_feedback_chain, fit_feedback_models
from .native_adapter import Native
from .run import PROJECT, digest, save_data, verify_freeze, write_json, write_rows
from .statistics import paired_interval


def train_all(run_dir, native, protocol):
    registration = protocol["feedback_chain"]
    for seed in protocol["training_seeds"]:
        directory = run_dir / "feedback_training" / f"seed_{seed}"
        directory.mkdir(parents=True, exist_ok=False)
        training = build_feedback_dataset(90000 + seed, registration["train_rows"], "train")
        development = build_feedback_dataset(100000 + seed, registration["development_rows"], "development")
        save_data(directory / "TRAIN.npz", training)
        save_data(directory / "DEVELOPMENT.npz", development)
        models, receipt = fit_feedback_models(training, development, native, directory)
        write_json(directory / "MODELS.json", models)
        with gzip.open(directory / "TRAINING.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, allow_nan=False)
        write_json(directory / "TRAINING_SUMMARY.json", {key: value for key, value in receipt.items() if key != "scopes"})
        print(json.dumps({"phase": "feedback_training", "seed": seed,
                          "heads": list(models["heads"]), "calibration": models["calibration"],
                          "wall_seconds": receipt["wall_ns"] / 1e9}), flush=True)


def confirm_all(run_dir, native, protocol):
    from .audit_feedback import audit_feedback_evaluation

    verify_freeze(run_dir, native)
    registration = protocol["feedback_chain"]
    summaries, utility, audits = [], {}, []
    for seed in protocol["training_seeds"]:
        started = time.perf_counter_ns()
        directory = run_dir / "feedback_confirmation" / f"seed_{seed}"
        directory.mkdir(parents=True, exist_ok=False)
        model_path = run_dir / "feedback_training" / f"seed_{seed}" / "MODELS.json"
        models = json.loads(model_path.read_text())
        data = build_feedback_dataset(110000 + seed, registration["confirmation_rows"], "confirmation")
        save_data(directory / "DATA.npz", data)
        result = evaluate_feedback_chain(models, data, native, directory)
        write_rows(directory / "ROWS.jsonl", result["rows"])
        metadata = {key: value for key, value in result.items() if key != "rows"}
        metadata["data_npz_sha256"] = digest(directory / "DATA.npz")
        metadata["frozen_model_file_sha256"] = digest(model_path)
        write_json(directory / "SUMMARY.json", metadata)
        audit = audit_feedback_evaluation(result, data, models, native, directory)
        write_json(directory / "AUDIT.json", audit)
        if not audit.get("passed", False):
            raise RuntimeError("Feedback evidence audit failed; all result files are retained")
        audits.append(audit)
        summaries.append(result["summary"])
        for arm in models["heads"]:
            rows = sorted((row for row in result["rows"] if row["arm"] == arm), key=lambda row: row["case"])
            utility.setdefault(arm, []).append(np.array([row["utility"] for row in rows]))
        print(json.dumps({"phase": "feedback_confirmation", "seed": seed,
                          "rows": len(result["rows"]), "audit_passed": True,
                          "wall_seconds_including_audit": (time.perf_counter_ns() - started) / 1e9}), flush=True)
    combined = {"scope": registration["scope"], "primary": False, "summary": {}, "contrasts": {},
                "independent_audits_passed": all(audit["passed"] for audit in audits),
                "population_advantage_established": False}
    for arm, values in utility.items():
        combined["summary"][arm] = {
            "mean_utility": float(np.asarray(values).mean()),
            "per_seed_mean_utility": np.asarray(values).mean(1).tolist(),
            "repair_count": sum(summary[arm]["repair_count"] for summary in summaries),
            "mean_action_cost": float(np.mean([summary[arm]["mean_action_cost"] for summary in summaries])),
            "native_ticks": sum(summary[arm]["native_ticks"] for summary in summaries),
            "action_disagreements_with_numeric": sum(summary[arm]["action_disagreements_with_numeric"] for summary in summaries),
            "state_value_disagreements_with_numeric": None if arm == "matched_history" else sum(
                summary[arm]["state_value_disagreements_with_numeric"] for summary in summaries),
            "wall_ns": sum(summary[arm]["wall_ns"] for summary in summaries),
            "cpu_ns": sum(summary[arm]["cpu_ns"] for summary in summaries)}
    for sequence, baseline in enumerate(("numeric", "matched_history", "zero", "state_reset")):
        result = paired_interval(np.asarray(utility["analytic_probability"]) - utility[baseline],
                                 protocol["statistics"]["bootstrap_replicates"], 81827 + sequence, .05)
        result["descriptive_only"] = True
        combined["contrasts"]["analytic_probability_vs_" + baseline] = result
    write_json(run_dir / "FEEDBACK_RESULTS.json", combined)
    verify_freeze(run_dir, native)
    return combined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "confirm"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
    with Native(args.native, args.receipt) as native:
        (train_all if args.phase == "train" else confirm_all)(args.run_dir, native, protocol)


if __name__ == "__main__":
    main()
