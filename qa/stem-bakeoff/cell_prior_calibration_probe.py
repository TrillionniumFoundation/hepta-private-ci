"""Post-hoc diagnosis of balanced-training versus natural calibration priors.

This separate probe never retrains a head or invokes an Encoder. Its protocol is
recorded before its own holdout scoring; all temperature choices use calibration
labels only. The original study remains unchanged. The probe is diagnostic,
not confirmatory evidence of a winning architecture or deployment qualification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_learning_metrics import calibrate_temperature, probabilities, task_metrics
from cell_learning_models import NumpyCellHead, canonical
from summarize_cell_study import inventory_digest, sha_file

GRID = (0.5, 1.0, 2.0, 4.0, 8.0)
SEEDS, MODES = (7, 17, 29), ("linear", "gated", "residual")
ARMS = ("original_temperature_only", "calibration_prior_only", "prior_corrected_temperature")
METRICS = ("forced_accuracy", "balanced_accuracy", "positive_recall", "nll", "brier_multiclass_sum",
           "ece10_equal_width", "coverage", "overall_success", "balanced_success")
CANDIDATES = {"granite97m": "granite97m", "embeddinggemma2_740m": "embeddinggemma2"}


def corrected_probability(logits, temperature, prior):
    prior = np.asarray(prior, dtype=np.float64)
    values = np.asarray(logits, dtype=np.float64)
    if (prior.shape != (2,) or not np.isfinite(prior).all() or np.any(prior <= 0)
            or not np.isclose(prior.sum(), 1, atol=1e-12, rtol=1e-12) or values.ndim != 2 or values.shape[1] != 2
            or type(temperature) not in (int, float) or not np.isfinite(temperature) or temperature <= 0):
        raise ValueError("valid binary prior, logits and temperature required")
    return probabilities(values / temperature + np.log(prior / 0.5))


def fit_prior_temperature(calibration_logits, calibration_labels):
    logits, labels = np.asarray(calibration_logits), np.asarray(calibration_labels)
    task_metrics(probabilities(logits), labels)
    if logits.shape[1] != 2:
        raise ValueError("binary diagnostic requires two output classes")
    counts = np.bincount(labels, minlength=2)
    prior = (counts + 1) / (len(labels) + 2)
    candidates = []
    for temperature in GRID:
        score = task_metrics(corrected_probability(logits, temperature, prior), labels)["nll"]
        candidates.append((score, abs(np.log(temperature)), temperature))
    best = min(candidates)
    return {"calibration_counts": counts.tolist(), "laplace_prior": prior.tolist(),
        "training_prior": [0.5, 0.5], "selected_temperature": float(best[2]),
        "calibration_nll": float(best[0]), "grid": list(GRID),
        "temperature_boundary_selected": best[2] in (min(GRID), max(GRID)),
        "grid_calibration_nll": [{"temperature": row[2], "nll": row[0]} for row in candidates]}


def evaluate_arms(logits, labels, original_temperature, fitted):
    prior = np.asarray(fitted["laplace_prior"])
    predicted = {ARMS[0]: probabilities(logits, original_temperature),
        ARMS[1]: np.broadcast_to(prior, (len(logits), 2)),
        ARMS[2]: corrected_probability(logits, fitted["selected_temperature"], prior)}
    return {name: task_metrics(value, labels, threshold=0.7) for name, value in predicted.items()}


def aggregate(records):
    groups = {}
    for record in records:
        for arm, metrics in record["metrics"].items():
            groups.setdefault((record["candidate"], record["mode"], arm), []).append(metrics)
    return [{"candidate": key[0], "mode": key[1], "arm": key[2], "task_count": 32,
             "task_seed_observations": len(rows),
             "metrics": {name: float(np.mean([row[name] for row in rows])) for name in METRICS}}
            for key, rows in sorted(groups.items())]


def run_probe(dataset, sealed_root, features_root, output):
    dataset_path, sealed, feature_root, root = map(Path, (dataset, sealed_root, features_root, output))
    raw = dataset_path.read_bytes()
    data = json.loads(raw)
    rows, tasks = data["rows"], data["selected_tasks"]
    cal_indices = [i for i, row in enumerate(rows) if row["split"] == "calibration"]
    test_indices = [i for i, row in enumerate(rows) if row["split"] == "holdout"]
    if len(tasks) != 32 or len(set(tasks)) != 32 or len(cal_indices) != 454 or len(test_indices) != 456:
        raise ValueError("fixed diagnostic needs all32 tasks and original454/456 calibration/test cohorts")
    root.mkdir(parents=True, exist_ok=False)
    protocol = {"schema": "hepta.cell-prior-calibration-diagnostic.v1", "classification": "post_hoc_diagnostic",
        "motivation": "original training samples balanced1:1; natural calibration priors differ",
        "registered_before_this_diagnostic_holdout_scoring": True, "original_study_changed": False,
        "tasks": tasks, "seeds": SEEDS, "modes": MODES, "training_examples": 128, "arms": ARMS,
        "calibration_prior": "Laplace (calibration_class_count+1)/(454+2)", "training_prior": [0.5, 0.5],
        "correction": "softmax(logits/T + log(calibration_prior/training_prior))",
        "prior_only": "constant calibration prior probabilities; no model signal",
        "temperature_grid": GRID, "selection": "calibration NLL only, then smallest absolute log temperature",
        "threshold": 0.7, "test_threshold_tuning": False, "encoder_forward_calls": 0, "optimizer_updates": 0,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(), "source_sha256": sha_file(__file__),
        "metrics": METRICS, "created_at_ns": time.time_ns(),
        "interpretation": "prior-shift assumption diagnostic; not a causal proof or architecture winner selection"}
    (root / "protocol.json").write_bytes(canonical(protocol) + b"\n")
    feature_matrices, identities, choices, input_files, seals = {}, {}, [], {}, []
    started = time.perf_counter_ns()
    for candidate, directory in CANDIDATES.items():
        study, feature_dir = sealed / directory / "study", feature_root / directory / "features"
        plan_path, receipt_path = study / "study-plan.json", feature_dir / "report.json"
        study_plan, receipt = json.loads(plan_path.read_bytes()), json.loads(receipt_path.read_bytes())
        archive_path = feature_dir / "features.npz"
        if (study_plan["dataset_sha256"] != protocol["dataset_sha256"] or study_plan["selected_tasks"] != tasks
                or sha_file(receipt_path) != study_plan["feature_receipt_sha256"]
                or receipt["plan"]["candidate"] != candidate or receipt["plan"]["source_ids"] != [r["source_id"] for r in rows]
                or sha_file(archive_path) != receipt["feature_archive_sha256"]):
            raise ValueError("frozen study, candidate, source order or feature archive differs")
        with np.load(archive_path, allow_pickle=False) as archive:
            features = archive["features"]
        if (list(features.shape) != receipt["feature_shape"] or features.dtype != np.float32
                or not np.isfinite(features).all()
                or hashlib.sha256(features.tobytes()).hexdigest() != receipt["feature_tensor_sha256"]):
            raise ValueError("feature tensor differs from original extraction")
        features.flags.writeable = False
        feature_matrices[candidate], identities[candidate] = features, receipt["feature_identity"]
        for path in (plan_path, receipt_path, archive_path):
            input_files[str(path)] = sha_file(path)
        for task in tasks:
            curve_dir = study / "curves" / task
            seal = json.loads((study / "completed" / (task + ".json")).read_bytes())
            if inventory_digest(curve_dir) != seal["inventory_sha256"]:
                raise ValueError("sealed head artifacts changed before calibration")
            seals.append((str(curve_dir), seal["inventory_sha256"]))
            report = json.loads((curve_dir / "report.json").read_bytes())
            y = np.array([rows[i]["labels"][task] for i in cal_indices])
            for seed in SEEDS:
                run = next(r for r in report["runs"] if r["seed"] == seed and r["budget"] == 128)
                if run["training_class_counts"] != [64, 64]:
                    raise ValueError("the balanced training-prior assumption does not hold")
                for mode in MODES:
                    original = run["arms"][mode]
                    model_dir = curve_dir / original["artifact"]
                    head = NumpyCellHead.load(model_dir, identities[candidate])
                    tensor_sha = head.digest()
                    cal_logits = head.predict_logits(features[cal_indices])
                    recovered_temperature, _ = calibrate_temperature(cal_logits, y)
                    if recovered_temperature != original["temperature"] or head.digest() != tensor_sha:
                        raise ValueError("original calibration or frozen head replay differs")
                    fitted = fit_prior_temperature(cal_logits, y)
                    choices.append({"candidate": candidate, "task": task, "seed": seed, "mode": mode,
                        "model_directory": str(model_dir), "tensor_sha256": tensor_sha,
                        "weights_sha256": sha_file(model_dir / "weights.npz"),
                        "original_temperature": original["temperature"], "fitted": fitted})
    if len(choices) != 576:
        raise ValueError("all576 predefined frozen model instances are required")
    frozen = {"protocol_sha256": sha_file(root / "protocol.json"), "choices": choices,
        "calibration_source_ids": [rows[i]["source_id"] for i in cal_indices],
        "input_files": input_files, "frozen_at_ns": time.time_ns(), "holdout_scoring_started": False}
    (root / "calibration-choices.json").write_bytes(canonical(frozen) + b"\n")
    records = []
    for choice in choices:
        candidate, task = choice["candidate"], choice["task"]
        head = NumpyCellHead.load(choice["model_directory"], identities[candidate])
        logits = head.predict_logits(feature_matrices[candidate][test_indices])
        labels = np.array([rows[i]["labels"][task] for i in test_indices])
        scores = evaluate_arms(logits, labels, choice["original_temperature"], choice["fitted"])
        if head.digest() != choice["tensor_sha256"] or sha_file(Path(choice["model_directory"]) / "weights.npz") != choice["weights_sha256"]:
            raise ValueError("inherited head tensors changed during the side probe")
        records.append({key: choice[key] for key in ("candidate", "task", "seed", "mode", "tensor_sha256")}
                       | {"metrics": scores})
    for path, digest in input_files.items():
        if sha_file(path) != digest:
            raise ValueError("frozen feature or study input changed during the side probe")
    if any(inventory_digest(Path(path)) != digest for path, digest in seals):
        raise ValueError("original sealed artifacts changed during the side probe")
    if sha_file(__file__) != protocol["source_sha256"] or sha_file(dataset_path) != protocol["dataset_sha256"]:
        raise ValueError("diagnostic code or target corpus changed")
    report = {"protocol": protocol, "calibration_choices_sha256": sha_file(root / "calibration-choices.json"),
        "inherited_models_verified_unchanged": len(choices), "original_task_inventories_verified": len(seals),
        "head_calibration_forward_calls": len(choices), "head_holdout_forward_calls": len(choices),
        "encoder_forward_calls": 0, "optimizer_updates": 0, "aggregate": aggregate(records),
        "task_metrics": records, "wall_ns": time.perf_counter_ns() - started,
        "task_seed_rows_are_independent_trials": False, "confirmatory_winner_qualification": False,
        "heldout_source_ids": [rows[i]["source_id"] for i in test_indices]}
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    manifest = {path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size} for path in sorted(root.iterdir())}
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "sealed-root", "features-root", "output"):
        parser.add_argument("--" + name, required=True)
    report = run_probe(**vars(parser.parse_args()))
    print(json.dumps({"models": report["inherited_models_verified_unchanged"],
                      "encoder_forwards": 0, "updates": 0, "wall_seconds": report["wall_ns"] / 1e9}))


if __name__ == "__main__":
    main()
