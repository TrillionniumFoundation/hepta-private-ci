"""Train on named development sources; confirmation data is not accepted here."""

import hashlib
import json
import time

import numpy as np
from scipy.optimize import minimize

from . import learners, task


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fit_readout(raw_train, raw_dev, target, dev_target, metadata):
    center, scale = raw_train.mean(0), raw_train.std(0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    x = np.column_stack([np.ones(len(raw_train)), (raw_train - center) / scale])
    z = np.column_stack([np.ones(len(raw_dev)), (raw_dev - center) / scale])
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    candidates = []
    for alpha in [0.1, 1.0, 10.0]:
        inverse = np.linalg.solve(x.T @ x + alpha * penalty + 1e-10 * np.eye(x.shape[1]), x.T)
        weights = inverse @ target
        residual = target - x @ weights
        # Correct mean log chi-square(1), then calibrate on development only.
        variance_weights = inverse @ (np.log(residual * residual + 1e-4) + 1.2703628454614782)
        predicted = z @ weights
        raw_variance = np.exp(np.clip(z @ variance_weights, -7.0, 5.0))
        variance_scale = np.clip(np.mean((dev_target - predicted) ** 2 / raw_variance, axis=0), 0.02, 50.0)
        score = learners.nll(dev_target, predicted, raw_variance * variance_scale)
        model = {**metadata, "kind": "readout", "center": center.tolist(), "scale": scale.tolist(),
                 "weights": weights.tolist(), "variance_weights": variance_weights.tolist(),
                 "variance_scale": variance_scale.tolist(), "ridge_alpha": alpha}
        candidates.append((score, model))
    selected = min(range(len(candidates)), key=lambda i: candidates[i][0])
    return candidates[selected][1], {
        "candidate_alphas": [0.1, 1.0, 10.0], "development_nll": [x[0] for x in candidates],
        "selected_index": selected, "readout_parameters": int(2 * x.shape[1] * target.shape[1] + target.shape[1]),
        "weight_l2": float(np.linalg.norm(candidates[selected][1]["weights"])),
        "variance_calibration_source": "development_only", "fit_rows": len(target),
        "independent_training_trajectories": len(target) // len(task.STAGES),
    }


def fit_models(training, development, seed, native=None):
    if training["split"] != "train" or development["split"] != "development":
        raise ValueError("Only explicitly labeled training and development data may fit models")
    h_train, y_train = task.combine_training(training)
    h_dev, y_dev = task.combine_training(development)
    rng = np.random.default_rng(seed)
    initial = np.array([rng.uniform(-0.15, 0.15), np.log(0.4), np.log(1.4)])
    objective_trace = []
    started = time.perf_counter()

    def objective(raw):
        parameters = [float(raw[0]), float(np.exp(raw[1])), float(np.exp(raw[2]))]
        model = {"kind": "filter", "parameters": parameters}
        means, variances = learners.predict(model, h_train)
        score = learners.nll(y_train, means, variances)
        objective_trace.append({"parameters": parameters, "composite_conditional_nll": score})
        return score

    result = minimize(objective, initial, method="L-BFGS-B",
                      bounds=[(-0.8, 0.8), (np.log(0.005), np.log(2.0)), (np.log(0.2), np.log(5.0))],
                      options={"maxiter": 120, "ftol": 1e-11, "gtol": 1e-6})
    parameters = [float(result.x[0]), float(np.exp(result.x[1])), float(np.exp(result.x[2]))]
    shared = {"planning_q": parameters[1], "planning_noise_scale": parameters[2]}
    analytic = {"kind": "filter", "parameters": parameters, **shared}
    models = {
        "analytic": analytic,
        "equivalent_gaussian": {**analytic, "equivalent_classical_implementation": True},
        "fixed": {"kind": "filter", "parameters": [0.0, 0.4, 1.4], **shared},
        "oracle": {"kind": "filter", "parameters": [0.12, task.PROCESS_VARIANCE, 1.0],
                   "planning_q": task.PROCESS_VARIANCE, "planning_noise_scale": 1.0,
                   "known_law_reference_only": True},
    }
    receipts = {
        "seed": int(seed), "training_dataset_sha256": task.dataset_digest(training),
        "development_dataset_sha256": task.dataset_digest(development),
        "initial_filter_parameters": [float(initial[0]), float(np.exp(initial[1])), float(np.exp(initial[2]))],
        "fitted_filter_parameters": parameters, "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message), "optimizer_iterations": int(result.nit),
        "optimizer_evaluations": int(result.nfev), "objective_trace": objective_trace,
        "filter_parameter_l2_change": float(np.linalg.norm(result.x - initial)),
        "filter_training_seconds": time.perf_counter() - started,
        "loss_scope": "composite conditional Gaussian score; correlated stages/horizons are not independent samples",
        "readouts": {},
    }
    for name, feature in [("history", "history"), ("pulse", "pulse"),
                          ("mean_drive", "mean_drive"), ("pulse_no_reset", "pulse_no_reset"),
                          ("native", "sparse")]:
        if feature == "sparse" and native is None:
            continue
        began = time.perf_counter()
        a = learners.raw_features(h_train, feature, parameters, seed, native)
        b = learners.raw_features(h_dev, feature, parameters, seed, native)
        metadata = {"feature": feature, "filter_parameters": parameters, "seed": int(seed), **shared}
        model, receipt = _fit_readout(a, b, y_train, y_dev, metadata)
        receipt["training_seconds"] = time.perf_counter() - began
        receipt["feature_width"] = a.shape[1]
        receipt["feature_bytes_sha256"] = hashlib.sha256(a.tobytes()).hexdigest()
        models[name] = model
        receipts["readouts"][name] = receipt
    receipts["model_sha256"] = _digest(models)
    receipts["native_baseline_trained"] = "native" in models
    receipts["frozen_after_development"] = True
    return models, receipts
