"""The two fixed four-parameter objectives and the sole paired comparison."""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

ARMS = ("mean_feature_head", "single_rollout_risk_head")


def objective(parameters, features, labels, arm):
    if arm == ARMS[0]:
        x, y = features.mean(axis=1), labels
    elif arm == ARMS[1]:
        x = features.reshape(-1, 3)
        y = np.repeat(labels, features.shape[1])
    else:
        raise ValueError("Unregistered objective")
    score = x @ parameters[:3] + parameters[3]
    residual = expit(score) - y
    value = np.mean(np.logaddexp(0, score) - y * score) + 0.0005 * np.dot(parameters[:3], parameters[:3])
    gradient = np.r_[x.T @ residual / len(y) + 0.001 * parameters[:3], residual.mean()]
    return float(value), gradient


def fit_head(features, labels, arm, config):
    options = config["optimizer"]["options"]
    fit = minimize(objective, np.zeros(4, dtype=np.float64), args=(features, labels, arm),
                   method="L-BFGS-B", jac=True, options=options)
    value, gradient = objective(fit.x, features, labels, arm)
    finite = bool(np.isfinite(fit.x).all() and np.isfinite(value) and np.isfinite(gradient).all())
    accepted = bool(finite and np.max(np.abs(gradient)) <= 1e-6)
    return {"arm": arm, "parameters": fit.x.tolist() if np.isfinite(fit.x).all() else None,
            "objective": value if np.isfinite(value) else None,
            "gradient": gradient.tolist() if np.isfinite(gradient).all() else None,
            "gradient_inf_norm": float(np.max(np.abs(gradient))) if finite else None,
            "numerically_accepted": accepted, "optimizer_success": bool(fit.success),
            "optimizer_status": int(fit.status), "message": str(fit.message),
            "iterations": int(fit.nit), "function_evaluations": int(fit.nfev),
            "gradient_evaluations": int(fit.njev)}


def losses(scores, labels):
    return np.logaddexp(0, scores) - labels[:, None] * scores


def evaluate(cache, heads):
    features, labels = cache["features"], cache["labels"]
    results = {}
    for arm in (*ARMS, "original_native_head"):
        if arm == "original_native_head":
            score = cache["native_logits"]
        else:
            head = heads[arm]
            if head.get("parameters") is None:
                results[arm] = {"available": False}
                continue
            p = np.asarray(head["parameters"])
            standardized = (features - head["train_mean"]) / head["train_scale"]
            score = standardized @ p[:3] + p[3]
        loss = losses(score, labels)
        if not np.isfinite(loss).all():
            results[arm] = {"available": False, "reason": "Non-finite evaluation loss"}
            continue
        by_example = loss.mean(axis=1)
        results[arm] = {"available": True, "mean_single_rollout_bce": float(by_example.mean()),
                        "loss_by_example": by_example.tolist(),
                        "single_rollout_accuracy": float(((score >= 0) == labels[:, None]).mean())}
    return results


def comparison(confirmations, heads, rng, config):
    all_accepted = all(head["numerically_accepted"] for pair in heads for head in pair.values())
    if any(not row[arm]["available"] for row in confirmations for arm in ARMS):
        return {"status": "numerically_incomplete", "passes_gate": False,
                "reason": "At least one registered head has no finite confirmation loss"}, None
    differences = np.asarray([np.asarray(row[ARMS[0]]["loss_by_example"])
                              - row[ARMS[1]]["loss_by_example"] for row in confirmations])
    replicates = np.empty(4000)
    for repetition in range(4000):
        chosen = rng.integers(3, size=3)
        replicates[repetition] = np.mean([
            differences[index, rng.integers(differences.shape[1], size=differences.shape[1])].mean()
            for index in chosen])
    lower = float(np.quantile(replicates, 0.05, method="linear"))
    means = differences.mean(axis=1)
    scientific = bool(lower > 0.02 and np.all(means > 0))
    return {"status": ("pass" if scientific else "negative_result") if all_accepted else "numerically_incomplete",
            "passes_gate": bool(scientific and all_accepted), "all_six_heads_numerically_accepted": all_accepted,
            "empirical_improvement_nats": float(means.mean()), "encoder_means": means.tolist(),
            "empirical_lower_endpoint": lower, "margin_nats": 0.02, "bootstrap_replicates": 4000,
            "interpretation": config["claims"]}, replicates
