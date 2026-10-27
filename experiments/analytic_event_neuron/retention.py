"""A bounded three-window adaptation and replay study, separate from persistence."""

import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

from . import learners, task
from .analytic import event_log_probs


def _load(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key]
                for key in archive.files}


def _prefix(data, count):
    n = len(data["ids"])
    return {key: value[:count] if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
            for key, value in data.items()}


def _adapt(model, pieces):
    if any(data["split"] not in ("train", "retention_train") for data in pieces):
        raise ValueError("Retention optimizers cannot receive evaluation datasets")
    pairs = [task.combine_training(data) for data in pieces]
    h = {key: np.concatenate([pair[0][key] for pair in pairs]) for key in pairs[0][0]}
    target = np.concatenate([pair[1] for pair in pairs])
    initial = np.array([model["parameters"][0], *np.log(model["parameters"][1:])])
    trace = []

    def loss(raw):
        fitted = {"kind": "filter", "parameters": [raw[0], *np.exp(raw[1:])]}
        mean, variance = learners.predict(fitted, h)
        value = learners.nll(target, mean, variance)
        trace.append(float(value))
        return value

    started = time.perf_counter_ns()
    result = minimize(loss, initial, method="L-BFGS-B",
                      bounds=[(-.8, .8), (np.log(.005), np.log(2)), (np.log(.2), np.log(5))],
                      options={"maxiter": 120, "ftol": 1e-11, "gtol": 1e-6})
    parameters = [float(result.x[0]), *np.exp(result.x[1:]).tolist()]
    updated = {**model, "parameters": parameters, "planning_q": parameters[1], "planning_noise_scale": parameters[2]}
    receipt = {"initial_parameters": model["parameters"], "final_parameters": parameters,
               "optimizer_success": bool(result.success), "optimizer_message": str(result.message),
               "training_trajectories": sum(len(data["ids"]) for data in pieces),
               "dataset_digests": [task.dataset_digest(data) for data in pieces],
               "objective_trace": trace, "training_wall_ns": time.perf_counter_ns() - started}
    return updated, receipt


def _scores(model, data):
    mean, variance = learners.predict(model, task.history(data))
    mean, variance, target = mean[:, 1:], variance[:, 1:], task.targets(data)[:, 1:]
    labels = task.event_labels(target)
    event = -np.take_along_axis(event_log_probs(mean, variance, task.LOWER, task.UPPER), labels[..., None], -1)[..., 0]
    gaussian = .5 * (np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance)
    return {"gaussian_nll": gaussian.mean(1), "event_nll": event.mean(1),
            "mse": ((target - mean) ** 2).mean(1), "mean": mean, "variance": variance,
            "targets": target, "ids": data["ids"]}


def evaluate_retention(run_dir, protocol):
    """Training at each window is prescribed; held-out outcomes never select a model."""
    run_dir = Path(run_dir)
    destination = run_dir / "retention"
    destination.mkdir(exist_ok=False)
    registration = protocol["retention"]
    records = []
    for seed in protocol["training_seeds"]:
        base_dir = run_dir / "training" / f"seed_{seed}"
        original = _load(base_dir / "TRAIN.npz")
        frozen = json.loads((base_dir / "MODELS.json").read_text())["analytic"]
        old_holdout = task.build_dataset(70000 + seed, registration["old_holdout_rows"], "retention_old_test")
        old_frozen = _scores(frozen, old_holdout)
        np.savez_compressed(destination / f"seed_{seed}_OLD.npz", **old_holdout)
        models = {"frozen": frozen, "online": dict(frozen), "replay": dict(frozen)}
        for window, law in enumerate(registration["windows"]):
            prefix = f"seed_{seed}_window_{window}"
            training = task.build_dataset(60000 + 100 * seed + window,
                                          registration["training_trajectories_per_window"], "retention_train", law)
            np.savez_compressed(destination / (prefix + "_TRAIN.npz"), **training)
            models["online"], online_receipt = _adapt(models["online"], [training])
            models["replay"], replay_receipt = _adapt(models["replay"], [
                _prefix(training, registration["new_rows_with_replay"]),
                _prefix(original, registration["replay_original_rows"])])
            # The new test is generated only after this window's training is complete.
            heldout = task.build_dataset(80000 + 100 * seed + window,
                                        registration["new_holdout_rows"], "retention_new_test", law)
            np.savez_compressed(destination / (prefix + "_NEW.npz"), **heldout)
            archive, scores = {}, {}
            for arm, model in models.items():
                old, new = _scores(model, old_holdout), _scores(model, heldout)
                scores[arm] = {"old": {key: float(old[key].mean()) for key in ("gaussian_nll", "event_nll", "mse")},
                               "new": {key: float(new[key].mean()) for key in ("gaussian_nll", "event_nll", "mse")},
                               "old_nll_degradation_from_initial": float((old["gaussian_nll"] - old_frozen["gaussian_nll"]).mean())}
                for domain, result in (("old", old), ("new", new)):
                    archive.update({arm + "__" + domain + "__" + key: value for key, value in result.items()})
            np.savez_compressed(destination / (prefix + "_SCORES.npz"), **archive)
            record = {"seed": seed, "window": window, "law": law, "models": models.copy(),
                      "training": {"online": online_receipt, "replay": replay_receipt}, "scores": scores}
            records.append(record)
            (destination / (prefix + ".json")).write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"phase": "retention", "seed": seed, "window": window, "law": law}), flush=True)
    summary = {"scope": registration["scope"], "windows": [], "matched_training_budget": True,
               "test_tuning": False, "population_long_term_guarantee": False}
    for window, law in enumerate(registration["windows"]):
        selected = [record for record in records if record["window"] == window]
        arms = {}
        for arm in ("frozen", "online", "replay"):
            arms[arm] = {"old_nll_degradation": float(np.mean([
                record["scores"][arm]["old_nll_degradation_from_initial"] for record in selected]))}
            for domain in ("old", "new"):
                arms[arm][domain] = {key: float(np.mean([record["scores"][arm][domain][key] for record in selected]))
                                     for key in ("gaussian_nll", "event_nll", "mse")}
        summary["windows"].append({"window": window, "law": law, "arms": arms})
    worst = max(window["arms"]["replay"]["old_nll_degradation"] for window in summary["windows"])
    last = summary["windows"][-1]["arms"]
    summary["replay_worst_window_old_nll_degradation"] = worst
    summary["replay_last_window_new_nll_difference_from_frozen"] = last["replay"]["new"]["gaussian_nll"] - last["frozen"]["new"]["gaussian_nll"]
    summary["passes_registered_bounded_retention_gate"] = bool(
        worst <= registration["old_gaussian_nll_degradation_margin"]
        and summary["replay_last_window_new_nll_difference_from_frozen"] <= 0)
    (run_dir / "RETENTION.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return summary
