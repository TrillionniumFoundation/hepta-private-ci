"""Group-disjoint calibration with a convex, nonnegative evidence scale.

This additive binary-task protocol admits scale zero (no evidence / infinite
temperature). It never receives a heldout cohort or chooses a heldout threshold.
"""

import hashlib

import numpy as np

from cell_learning_baselines import normalized_text
from cell_learning_metrics import probabilities
from cell_learning_models import canonical


def group_weights(rows):
    counts = {}
    for row in rows:
        counts[row["group_id"]] = counts.get(row["group_id"], 0) + 1
    return np.array([1.0 / counts[row["group_id"]] for row in rows])


def calibration_partition(rows, seed=20261024, input_content_sha256=None):
    """Keep connected group/text duplicates together; partition without labels."""
    parent, seen = list(range(len(rows))), {}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, row in enumerate(rows):
        predictor = (input_content_sha256[row["source_id"]] if input_content_sha256 is not None
                     else normalized_text(row["text"]))
        for key in (("group", row["group_id"]), ("predictor", predictor)):
            if key in seen:
                parent[find(i)] = find(seen[key])
            seen[key] = i
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=lambda ids: hashlib.sha256(canonical(
        [seed, sorted(rows[i]["source_id"] for i in ids)])).hexdigest())
    if len(ordered) < 2:
        raise ValueError("calibration requires at least two disjoint source components")
    middle = len(ordered) // 2
    return (np.array(sorted(i for ids in ordered[:middle] for i in ids)),
            np.array(sorted(i for ids in ordered[middle:] for i in ids)))


def _inputs(logits, labels, weights):
    z, y = np.asarray(logits, dtype=np.float64), np.asarray(labels)
    w = np.ones(len(y)) if weights is None else np.asarray(weights, dtype=np.float64)
    if (z.ndim != 2 or z.shape != (len(y), 2) or not 1 <= len(y) <= 16384
            or y.dtype.kind not in "iu" or np.any((y < 0) | (y > 1))
            or w.shape != y.shape or not np.isfinite(z).all()
            or not np.isfinite(w).all() or np.any(w <= 0)):
        raise ValueError("finite binary logits, labels and positive weights required")
    return z, y, w


def smoothed_prior(labels, weights=None):
    y = np.asarray(labels)
    _, y, w = _inputs(np.zeros((len(y), 2)), y, weights)
    counts = np.bincount(y, weights=w, minlength=2)
    return (counts + 1) / (w.sum() + 2)


def weighted_nll(logits, labels, weights=None):
    z, y, w = _inputs(logits, labels, weights)
    return float(np.average(-np.log(np.clip(probabilities(z)[np.arange(len(y)), y],
                                          1e-15, 1)), weights=w))


def prior_corrected_logits(logits, training_prior, target_prior):
    return np.asarray(logits) + np.log(np.asarray(target_prior) / np.asarray(training_prior))


def fit_calibrator(logits, labels, weights=None, *, max_iterations=100):
    """Fit Platt scale+bias by projected Newton steps and bounded line search.

    Each source group contributes total weight one. Two pseudo observations at
    the weighted mean score give a Laplace-smoothed prior at scale zero. The
    fixed ridge on evidence scale is 0.001; alpha is in [0,32], bias in [-12,12].
    """
    z, y, w = _inputs(logits, labels, weights)
    if type(max_iterations) is not int or not 1 <= max_iterations <= 100:
        raise ValueError("bounded optimizer iterations required")
    raw = z[:, 1] - z[:, 0]
    center = float(np.average(raw, weights=w))
    scale = max(float(np.sqrt(np.average((raw - center)**2, weights=w))), 1e-8)
    x = (raw - center) / scale
    prior = smoothed_prior(y, w)
    theta = np.array([0.0, np.log(prior[1] / prior[0])])
    low, high = np.array([0.0, -12.0]), np.array([32.0, 12.0])
    def objective(t):
        s = t[0] * x + t[1]
        return float(np.sum(w * (np.logaddexp(0, s) - y * s))
                     + np.logaddexp(0, t[1]) + np.logaddexp(0, -t[1])
                     + 0.0005 * t[0]**2)
    initial, converged, calls = objective(theta), False, 1
    projected_norm, completed = None, 0
    for iteration in range(max_iterations):
        completed = iteration + 1
        p = 1 / (1 + np.exp(-np.clip(theta[0] * x + theta[1], -700, 700)))
        p0 = 1 / (1 + np.exp(-theta[1]))
        error, variance = w * (p - y), w * p * (1 - p)
        gradient = np.array([error @ x + 0.001 * theta[0], error.sum() + 2*p0 - 1])
        projected = gradient.copy()
        projected[((theta <= low) & (gradient > 0)) | ((theta >= high) & (gradient < 0))] = 0
        projected_norm = float(np.abs(projected).max())
        if projected_norm / (w.sum() + 2) < 1e-8:
            converged = True
            break
        hessian = np.array([[variance @ (x*x) + 0.001, variance @ x],
                            [variance @ x, variance.sum() + 2*p0*(1-p0)]])
        direction = -np.linalg.solve(hessian + np.eye(2)*1e-12, gradient)
        if gradient @ (np.clip(theta + direction, low, high) - theta) >= 0:
            direction = -projected / max(float(np.linalg.norm(projected)), 1.0)
        old, moved = objective(theta), False
        calls += 1
        for exponent in range(24):
            candidate = np.clip(theta + direction * 0.5**exponent, low, high)
            value = objective(candidate)
            calls += 1
            if value <= old + 1e-4 * (gradient @ (candidate - theta)):
                if np.max(np.abs(candidate - theta)) <= 1e-12:
                    break
                theta, moved = candidate, True
                break
        if not moved:
            break
    result = {"schema": "hepta.group-binary-calibration.v2", "alpha": float(theta[0]),
              "bias": float(theta[1]), "center": center, "scale": scale,
              "inverse_temperature": float(theta[0] / scale),
              "temperature": float(scale / theta[0]) if theta[0] > 0 else None,
              "prior": prior.tolist(), "group_mass": float(w.sum()), "rows": len(y),
              "class_support": np.bincount(y, minlength=2).tolist(),
              "converged": converged, "iterations": completed,
              "projected_gradient_max": projected_norm, "objective_calls": calls,
              "projected_gradient_per_group": projected_norm / float(w.sum() + 2),
              "convergence_tolerance_per_group": 1e-8,
              "penalized_objective_initial": initial, "penalized_objective_final": objective(theta),
              "scale_zero_no_evidence": bool(theta[0] == 0),
              "upper_scale_boundary": bool(theta[0] == 32),
              "bias_boundary": bool(abs(theta[1]) == 12), "fitted_degrees_of_freedom": 2,
              "stored_scalars": 4, "fit_source": "calibration_half_only"}
    result["weighted_nll"] = weighted_nll(apply_calibrator_logits(z, result), y, w)
    return result


def apply_calibrator_logits(logits, fitted):
    z = np.asarray(logits, dtype=np.float64)
    if z.ndim != 2 or z.shape[1] != 2 or not np.isfinite(z).all():
        raise ValueError("finite binary logits required")
    values = np.array([fitted[k] for k in ("alpha", "bias", "center", "scale")])
    if not np.isfinite(values).all() or not 0 <= values[0] <= 32 or values[3] <= 0:
        raise ValueError("invalid frozen calibrator")
    score = fitted["alpha"] * ((z[:, 1] - z[:, 0] - fitted["center"]) / fitted["scale"]) + fitted["bias"]
    return np.column_stack((np.zeros(len(z)), score))


def discrimination_metrics(probability, labels, prior):
    """Secondary ranking and fixed prior-threshold decisions; no threshold fit."""
    p, y = np.asarray(probability), np.asarray(labels)
    _inputs(np.log(np.maximum(p, 1e-300)), y, None)
    predicted = p[:, 1] > float(prior[1]) + 1e-12
    recalls = [float((predicted[y == k] == k).mean()) if np.any(y == k) else None
               for k in (0, 1)]
    order = np.argsort(p[:, 1], kind="stable")
    ranks = np.empty(len(y), dtype=float)
    _, starts, counts = np.unique(p[order, 1], return_index=True, return_counts=True)
    for start, count in zip(starts, counts):
        ranks[order[start:start+count]] = start + (count + 1) / 2
    positive, negative = int(y.sum()), int(len(y) - y.sum())
    auc = ((ranks[y == 1].sum() - positive*(positive+1)/2) / (positive*negative)
           if positive and negative else None)
    return {"auroc": float(auc) if auc is not None else None,
            "calibration_prior_threshold": float(prior[1]),
            "balanced_accuracy_at_prior_threshold": float(np.mean(recalls)) if all(r is not None for r in recalls) else None,
            "positive_recall_at_prior_threshold": recalls[1]}
