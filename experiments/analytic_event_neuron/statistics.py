"""Registered paired, trajectory-level summaries; no fitting or model selection."""

import json
from pathlib import Path

import numpy as np


def analysis_arrays(prediction_rows, control_rows):
    arrays = {}
    for kind, rows in (("prediction", prediction_rows), ("control", control_rows)):
        for arm in sorted({row["arm"] for row in rows}):
            selected = sorted((row for row in rows if row["arm"] == arm), key=lambda row: row["case"])
            arrays[f"{kind}_ids__{arm}"] = np.array([row["case"] for row in selected])
            if kind == "prediction":
                for metric in ("nll", "brier"):
                    arrays[f"{metric}__{arm}"] = np.array([np.mean(row[metric]) for row in selected])
                arrays[f"probabilities__{arm}"] = np.array([row["probabilities"] for row in selected])
                arrays[f"labels__{arm}"] = np.array([row["labels"] for row in selected])
                arrays[f"mse__{arm}"] = np.array([
                    np.mean((np.array(row["mean"]) - row["targets"]) ** 2) for row in selected])
                arrays[f"standardized_error__{arm}"] = np.array([
                    (np.array(row["targets"]) - row["mean"]) / np.sqrt(row["variance"]) for row in selected])
            else:
                for metric in ("utility", "paid_cost", "elapsed_ns", "cpu_ns", "severe_loss", "squared_error"):
                    arrays[f"{metric}__{arm}"] = np.array([row[metric] for row in selected])
                arrays[f"actions__{arm}"] = np.array(["/".join(row["actions"]) for row in selected])
    return arrays


def calibration(probabilities, labels):
    """Equal-width classwise calibration; horizons remain dependent measurements."""
    p, y = probabilities.reshape(-1, 3), labels.reshape(-1)
    bins, class_error = [], []
    for category in range(3):
        observed = y == category
        assignment = np.minimum((p[:, category] * 10).astype(int), 9)
        error = 0.0
        for index in range(10):
            selected = assignment == index
            n = int(selected.sum())
            forecast = float(p[selected, category].mean()) if n else None
            frequency = float(observed[selected].mean()) if n else None
            if n:
                error += n / len(p) * abs(forecast - frequency)
            bins.append({"event": category, "bin": index, "count": n,
                         "mean_probability": forecast, "frequency": frequency})
        class_error.append(error)
    return {"classwise_ece": float(np.mean(class_error)), "event_ece": class_error,
            "bins": bins, "independent_sample_count": len(labels),
            "horizon_measurements_per_trajectory": labels.shape[1]}


def paired_interval(differences, replicates, seed, alpha):
    """Resample training seeds, then paired whole trajectories within each seed."""
    differences = np.asarray(differences, dtype=float)
    if differences.ndim != 2 or not np.isfinite(differences).all():
        raise ValueError("Expected a finite seed-by-trajectory paired matrix")
    rng = np.random.default_rng(seed)
    training_seeds, trajectories = differences.shape
    boot = np.empty(replicates)
    for start in range(0, replicates, 200):
        count = min(200, replicates - start)
        seeds = rng.integers(training_seeds, size=(count, training_seeds, 1))
        cases = rng.integers(trajectories, size=(count, training_seeds, trajectories))
        boot[start:start + count] = differences[seeds, cases].mean(axis=(1, 2))
    return {"mean_difference": float(differences.mean()),
            "interval": np.quantile(boot, [alpha / 2, 1 - alpha / 2]).tolist(),
            "per_seed_mean_difference": differences.mean(1).tolist(),
            "training_seed_count": training_seeds, "trajectories_per_seed": trajectories,
            "replicates": replicates, "interval_alpha": alpha,
            "method": "paired two-stage seed/whole-trajectory percentile bootstrap"}


def summarize(run_dir, protocol):
    run_dir = Path(run_dir)
    index = json.loads((run_dir / "RUN_INDEX.json").read_text())
    loaded = {}
    for entry in index["scopes"]:
        with np.load(run_dir / entry["analysis_path"], allow_pickle=False) as archive:
            loaded[(entry["training_seed"], entry["law"])] = {key: archive[key] for key in archive.files}
    seeds = protocol["training_seeds"]
    laws = [protocol["laws"]["primary"], *protocol["laws"]["mismatch"]]
    output = {"schema": "hepta.analytic-event.results.v1", "laws": {}, "primary_contrasts": {},
              "mismatch_contrasts": {}, "secondary_contrasts": {},
              "sampling_limit": "Five training seeds; bootstrap intervals are empirical, not finite-sample guarantees."}
    for law in laws:
        scopes = [loaded[(seed, law)] for seed in seeds]
        arms = sorted(key.split("__", 1)[1] for key in scopes[0] if key.startswith("utility__"))
        metrics = {}
        for arm in arms:
            item = {}
            for metric in ("utility", "paid_cost", "squared_error", "severe_loss", "elapsed_ns", "cpu_ns"):
                values = np.concatenate([scope[f"{metric}__{arm}"] for scope in scopes])
                item[metric] = {"mean": float(values.mean()), "q05": float(np.quantile(values, .05)),
                                "median": float(np.median(values)), "q95": float(np.quantile(values, .95))}
            actions = np.concatenate([scope[f"actions__{arm}"] for scope in scopes])
            unique, counts = np.unique(actions, return_counts=True)
            item["actions"] = dict(zip(unique.tolist(), counts.tolist()))
            if f"nll__{arm}" in scopes[0]:
                for metric in ("nll", "brier", "mse"):
                    item[metric] = float(np.concatenate([scope[f"{metric}__{arm}"] for scope in scopes]).mean())
                p = np.concatenate([scope[f"probabilities__{arm}"] for scope in scopes])
                y = np.concatenate([scope[f"labels__{arm}"] for scope in scopes])
                z = np.concatenate([scope[f"standardized_error__{arm}"] for scope in scopes])
                item["calibration"] = calibration(p, y)
                item["gaussian_interval_coverage"] = {
                    "nominal_68.27": float(np.mean(abs(z) <= 1)),
                    "nominal_90": float(np.mean(abs(z) <= 1.6448536269514722)),
                    "nominal_95": float(np.mean(abs(z) <= 1.959963984540054))}
            metrics[arm] = item
        output["laws"][law] = metrics
    registered = protocol["statistics"]

    def compare(candidate, baseline, law, sequence, primary=False):
        delta = []
        for seed in seeds:
            scope = loaded[(seed, law)]
            if not np.array_equal(scope[f"control_ids__{candidate}"], scope[f"control_ids__{baseline}"]):
                raise ValueError("Unpaired environment trajectories")
            delta.append(scope[f"utility__{candidate}"] - scope[f"utility__{baseline}"])
        alpha = registered["family_alpha"] / registered["primary_family_size"] if primary else .05
        result = paired_interval(delta, registered["bootstrap_replicates"],
                                 registered["bootstrap_seed"] + sequence, alpha)
        result.update({"candidate": candidate, "baseline": baseline, "law": law, "primary": primary})
        if primary:
            result["passes_registered_superiority"] = bool(
                result["interval"][0] > registered["minimum_useful_net_utility_gain"]
                and min(result["per_seed_mean_difference"]) > 0)
        else:
            result["descriptive_only"] = True
        return result

    for sequence, contrast in enumerate(protocol["primary_contrasts"]):
        output["primary_contrasts"][contrast["id"]] = compare(
            contrast["candidate"], contrast["baseline"], "gaussian", sequence, True)
        for offset, law in enumerate(laws[1:], 1):
            result = compare(contrast["candidate"], contrast["baseline"], law, 100 * offset + sequence)
            result["empirical_lower_above_negative_margin"] = result["interval"][0] > -registered["mismatch_noninferiority_margin"]
            result["population_noninferiority_established"] = False
            if law == "student_t":
                result["limitation"] = "Student-t(4) has no fourth moment; squared-loss bootstrap coverage is not guaranteed."
            output["mismatch_contrasts"][law + ":" + contrast["id"]] = result
    secondaries = [("pulse", "mean_drive"), ("pulse", "pulse_no_reset"),
                   ("analytic", "equivalent_gaussian"), ("analytic", "fixed"), ("analytic", "oracle")]
    secondaries += [("analytic", arm) for arm in ("always_stop", "always_repair", "always_wait", "always_wait_repair")]
    for sequence, (candidate, baseline) in enumerate(secondaries):
        output["secondary_contrasts"][candidate + "_vs_" + baseline] = compare(
            candidate, baseline, "gaussian", 1000 + sequence)
    return output
