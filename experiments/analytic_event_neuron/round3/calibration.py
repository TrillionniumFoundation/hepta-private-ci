"""Public-history calibration with an explicitly empirical retention constraint.

The learned Gaussian moment head is not the pointwise protected Round 2 head.
Both remain available, and their guarantees are reported separately.
"""

from copy import deepcopy
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from .. import learners, statistics, task
from ..analytic import event_probs
from ..round2 import adaptation


SCHEMA = "hepta.analytic-event.empirical-calibration.v1"
Q24 = 1 << 24
STRENGTHS = tuple(float(x) for x in np.linspace(0, 1, 11))
INFLATIONS = (1.0, 1.025, 1.05, 1.1, 1.2)
TRAIN_SPLITS = ("train", "retention_train")


def public_history(history):
    """Condition only on observed values, times, masks and sensor variances."""
    adaptation._validate_history(history)
    active = np.asarray(history["occupied"], dtype=bool)
    seen = active & np.asarray(history["mask"], dtype=bool)
    return {"obs": np.where(seen, history["obs"], 0.0),
            "times": np.where(active, history["times"], 0.0),
            "mask": seen, "occupied": active,
            "obs_var": np.where(seen, history["obs_var"], 1.0),
            "ids": np.asarray(history.get("ids", np.arange(len(active))))}


def dense_log_likelihood(model, history):
    """Independent Gaussian covariance solve for the public sensor likelihood."""
    drift, diffusion, noise = model["parameters"]
    values = []
    for row in range(len(history["obs"])):
        seen = history["occupied"][row] & history["mask"][row]
        times = history["times"][row, seen]
        residual = history["obs"][row, seen] - drift * times
        covariance = 1.0 + diffusion * np.minimum(times[:, None], times[None, :])
        covariance += np.diag(noise * history["obs_var"][row, seen])
        sign, logdet = np.linalg.slogdet(covariance)
        if sign != 1:
            raise ValueError("Public Gaussian covariance is not positive definite")
        values.append(-.5 * (len(times) * np.log(2 * np.pi) + logdet
                              + residual @ np.linalg.solve(covariance, residual)))
    return np.asarray(values)


def components(anchor, adaptive, history, classical=False):
    adaptation._validate_filter(anchor)
    adaptation._validate_filter(adaptive)
    history = public_history(history)
    a, b = deepcopy(anchor), deepcopy(adaptive)
    if classical:
        a["equivalent_classical_implementation"] = True
        b["equivalent_classical_implementation"] = True
    m0, v0 = learners.predict(a, history)
    m1, v1 = learners.predict(b, history)
    likelihood = dense_log_likelihood if classical else adaptation.public_log_likelihood
    difference = likelihood(b, history) - likelihood(a, history)
    feature = np.column_stack([np.ones(len(m0)), np.clip(difference / 4.0, -2.0, 2.0)])
    return m0, v0, m1, v1, feature


def candidate_moments(raw, component):
    m0, v0, m1, v1, features = component
    weight = expit(features @ np.asarray(raw[:2]))[:, None]
    difference = m1 - m0
    mean = m0 + weight * difference
    variance = ((1 - weight) * v0 + weight * v1
                + weight * (1 - weight) * difference ** 2) * np.exp(raw[2:])
    return mean, variance, weight


def objective_gradient(raw, component, target, penalty=.001):
    """Composite Gaussian NLL and analytic derivatives for six fitted values."""
    mean, variance, weight = candidate_moments(raw, component)
    m0, v0, m1, v1, features = component
    error, difference = mean - target, m1 - m0
    loss = .5 * (np.log(2 * np.pi * variance) + error ** 2 / variance)
    count = target.size
    mean_gradient = error / variance
    variance_gradient = .5 * (1 / variance - error ** 2 / variance ** 2)
    dw = (mean_gradient * difference + variance_gradient * np.exp(raw[2:])
          * (v1 - v0 + (1 - 2 * weight) * difference ** 2)).sum(1)
    gradient = np.concatenate([
        features.T @ (dw * weight[:, 0] * (1 - weight[:, 0])) / count,
        (variance_gradient * variance).sum(0) / count])
    raw = np.asarray(raw)
    return float(loss.mean() + penalty * np.sum(raw ** 2)), gradient + 2 * penalty * raw


def fit_model(anchor, adaptive, pieces):
    """Fit on labelled training trajectories, without hidden regime indicators."""
    if len(pieces) != 2 or any(data["split"] not in TRAIN_SPLITS for data in pieces):
        raise ValueError("Exactly two explicitly labelled training collections are required")
    if len(pieces[0]["ids"]) != len(pieces[1]["ids"]):
        raise ValueError("Old and current training collections must have equal trajectory weight")
    pairs = [task.combine_training(data) for data in pieces]
    history = {key: np.concatenate([pair[0][key] for pair in pairs]) for key in pairs[0][0]}
    target = np.concatenate([pair[1] for pair in pairs])
    component = components(anchor, adaptive, history)
    initial = np.zeros(6)
    trace = []

    def objective(raw):
        value, gradient = objective_gradient(raw, component, target)
        trace.append({"parameters": raw.tolist(), "penalized_nll": value,
                      "gradient_norm": float(np.linalg.norm(gradient))})
        return value, gradient

    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    fitted = minimize(objective, initial, jac=True, method="L-BFGS-B",
        bounds=[(-6.0, 6.0), (0.0, 6.0)] + [(np.log(.75), np.log(2.0))] * 4,
        options={"maxiter": 200, "ftol": 1e-12, "gtol": 1e-7})
    model = {"schema": SCHEMA, "kind": "empirical_calibration", "anchor": deepcopy(anchor),
             "adaptive": deepcopy(adaptive), "parameters": fitted.x.tolist(),
             "strength": 1.0, "variance_inflation": 1.0,
             "classical": False, "output_quantization": None,
             "planning_q": float(anchor["planning_q"]),
             "planning_noise_scale": float(anchor["planning_noise_scale"]),
             "universal_pointwise_retention_guarantee": False,
             "planning_scope": "anchor process/noise plug-in; calibration evaluation is predictive"}
    receipt = {"initial_parameters": initial.tolist(), "fitted_parameters": fitted.x.tolist(),
               "parameter_l2_change": float(np.linalg.norm(fitted.x - initial)),
               "optimizer_success": bool(fitted.success), "optimizer_message": str(fitted.message),
               "optimizer_iterations": int(fitted.nit), "objective_trace": trace,
               "training_trajectories": sum(len(data["ids"]) for data in pieces),
               "dataset_digests": [task.dataset_digest(data) for data in pieces],
               "training_wall_ns": time.perf_counter_ns() - started,
               "training_parent_cpu_ns": time.process_time_ns() - cpu,
               "hidden_regime_input": False, "targets_only_in_loss": True}
    return model, receipt


def predict_details(model, history):
    if model.get("kind") != "empirical_calibration":
        return adaptation.predict_details(model, public_history(history))
    if model.get("schema") != SCHEMA or model.get("universal_pointwise_retention_guarantee") is not False:
        raise ValueError("Unrecognized empirical calibration contract")
    raw = np.asarray(model["parameters"], dtype=float)
    strength, inflation = float(model["strength"]), float(model["variance_inflation"])
    if (raw.shape != (6,) or not np.isfinite(raw).all() or not 0 <= strength <= 1
            or not np.isfinite(inflation) or inflation < 1):
        raise ValueError("Invalid fitted parameters or declared interpolation")
    component = components(model["anchor"], model["adaptive"], history, model["classical"])
    mean, variance, weight = candidate_moments(raw, component)
    m0, v0 = component[:2]
    delta = mean - m0
    mean = m0 + strength * delta
    variance = ((1 - strength) * v0 + strength * variance
                + strength * (1 - strength) * delta ** 2) * inflation
    if (not np.isfinite(mean).all() or not np.isfinite(variance).all() or np.any(variance <= 0)):
        raise ValueError("Calibration moments must remain finite with positive variance")
    details = {"adaptive_weight": weight[:, 0], "empirical_strength": strength,
               "variance_inflation": inflation, "pointwise_retention_certificate": None}
    if model["output_quantization"] == "q24_parameters_nearest":
        if np.any(np.abs(mean) > 1e4) or np.any(variance < 1e-4) or np.any(variance > 100):
            raise ValueError("Empirical Q24 parameter domain is |mean|<=1e4 and variance in [1e-4,100]")
        mq = np.rint(mean * Q24).astype(np.int64)
        vq = np.maximum(1, np.rint(variance * Q24)).astype(np.int64)
        mean, variance = mq / Q24, vq / Q24
        details.update({"mean_q24": mq, "variance_q24": vq,
                        "native_typed_domain_mask": (np.abs(mean) <= 8) & (variance <= 8)})
    elif model["output_quantization"] is not None:
        raise ValueError("Unknown parameter quantization")
    return mean, variance, details


def predict(model, history):
    mean, variance, _ = predict_details(model, history)
    return mean, variance


def select_model(model, old_development, new_development, old_nll_margin=.02):
    """Choose from the fixed 55-point grid using only development outcomes.

    The paired SE reserve is a selection heuristic, not a simultaneous bound.
    Every candidate and score is retained; strength=0/inflation=1 is the anchor.
    """
    if (old_nll_margin != .02 or any(data["split"] != "calibration_development"
                                   for data in (old_development, new_development))):
        raise ValueError("Selection requires development-only inputs and the original margin")
    contexts = [task.history(data) for data in (old_development, new_development)]
    targets = [task.targets(data)[:, 1:] for data in (old_development, new_development)]
    cached = []
    for history in contexts:
        component = components(model["anchor"], model["adaptive"], history)
        mean, variance, _ = candidate_moments(np.asarray(model["parameters"]), component)
        cached.append((component[0][:, 1:], component[1][:, 1:], mean[:, 1:], variance[:, 1:]))
    old_m, old_v = cached[0][:2]
    old_anchor_loss = .5 * (np.log(2 * np.pi * old_v) + (targets[0] - old_m) ** 2 / old_v)
    candidates = []
    for strength in STRENGTHS:
        for inflation in INFLATIONS:
            scores = []
            for domain, ((m0, v0, mean, variance), target) in enumerate(zip(cached, targets)):
                delta = mean - m0
                mean = m0 + strength * delta
                variance = ((1 - strength) * v0 + strength * variance
                            + strength * (1 - strength) * delta ** 2) * inflation
                loss = .5 * (np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance)
                score = {"gaussian_nll": float(loss.mean()),
                    "classwise_ece": statistics.calibration(event_probs(mean, variance, task.LOWER, task.UPPER),
                                                              task.event_labels(target))["classwise_ece"],
                    "coverage95": float(np.mean(abs(target - mean) <= 1.959963984540054 * np.sqrt(variance)))}
                if domain == 0:
                    difference = (loss - old_anchor_loss).mean(1)
                    score["paired_nll_change"] = float(difference.mean())
                    score["paired_standard_error"] = float(difference.std(ddof=1) / np.sqrt(len(difference)))
                    score["selection_upper_heuristic"] = score["paired_nll_change"] + 1.645 * score["paired_standard_error"]
                scores.append(score)
            candidates.append({"strength": strength, "variance_inflation": inflation,
                "old": scores[0], "new": scores[1],
                "eligible": bool(scores[0]["selection_upper_heuristic"] <= old_nll_margin)})
    eligible = [i for i, candidate in enumerate(candidates) if candidate["eligible"]]
    if not eligible:
        raise AssertionError("Unchanged anchor must be feasible")
    chosen = min(eligible, key=lambda i: (candidates[i]["new"]["gaussian_nll"], i))
    selected = deepcopy(model)
    for key in ("strength", "variance_inflation"):
        selected[key] = candidates[chosen][key]
    receipt = {"candidates": candidates, "selected_index": chosen, "grid_size": len(candidates),
               "old_nll_margin": old_nll_margin, "selection_only_heuristic": True,
               "universal_pointwise_retention_guarantee": False,
               "development_dataset_digests": [task.dataset_digest(data)
                                                for data in (old_development, new_development)]}
    return selected, receipt
