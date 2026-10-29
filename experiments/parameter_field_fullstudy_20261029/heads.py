"""Fixed linear advantage heads; calibration is an empirical screen, not a bound."""

import numpy as np


def fit_head(features, advantages, fit_mask, calibration_mask, baseline=2):
    if type(baseline) is not int or baseline not in range(4):
        raise ValueError("Invalid baseline action")
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(advantages, dtype=np.float64)
    fit = np.asarray(fit_mask, dtype=bool)
    cal = np.asarray(calibration_mask, dtype=bool)
    if x.ndim != 2 or y.shape != (len(x), 4) or fit.shape != (len(x),):
        raise ValueError("Invalid head bank shape")
    if cal.shape != fit.shape or np.any(fit & cal) or not fit.any() or not cal.any():
        raise ValueError("Fit and calibration must be distinct nonempty partitions")
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(y[:, baseline] != 0):
        raise ValueError("Nonfinite bank or nonzero baseline advantage")
    mean, scale = x[fit].mean(0), x[fit].std(0)
    constant_coordinates = int(np.sum(scale < 1e-8))
    scale = np.maximum(scale, 1e-8)
    z = (x - mean) / scale
    # A free intercept and fixed ridge=1 on coefficients, using the dual form.
    intercept = y[fit].mean(0)
    gram = z[fit] @ z[fit].T
    alpha = np.linalg.solve(gram + np.eye(fit.sum()), y[fit] - intercept)
    coefficients = z[fit].T @ alpha
    coefficients[:, baseline], intercept[baseline] = 0., 0.
    predicted = z[cal] @ coefficients + intercept
    error = predicted - y[cal]
    nonbaseline = [i for i in range(4) if i != baseline]
    threshold = max(0., float(error[:, nonbaseline].max()))
    attainable = np.maximum(0., y[cal].max(1))
    rmse = float(np.sqrt(np.mean(error[:, nonbaseline] ** 2)))
    mean_gain = float(attainable.mean())
    return {
        "mean": mean, "scale": scale, "coefficients": coefficients,
        "intercept": intercept, "threshold": threshold, "baseline": int(baseline),
        "fit_count": int(fit.sum()), "calibration_count": int(cal.sum()),
        "dimension": x.shape[1], "ridge": 1., "certificate": False,
        "fit_max_standardized_norm": float(np.linalg.norm(z[fit], axis=1).max()),
        "diagnostics": {
            "calibration_rmse": rmse, "mean_attainable_gain": mean_gain,
            "rmse_over_mean_attainable_gain": rmse / mean_gain if mean_gain > 0 else None,
            "calibration_action_accuracy": float(np.mean(predicted.argmax(1) == y[cal].argmax(1))),
            "calibration_action_regret": float(np.mean(y[cal].max(1) - y[cal][np.arange(cal.sum()), predicted.argmax(1)])),
            "calibration_max_overprediction": threshold,
            "constant_coordinates": constant_coordinates,
            "fit_design_rank": int(np.linalg.matrix_rank(gram)),
            "regularized_gram_condition": float(np.linalg.cond(gram + np.eye(fit.sum()))),
            "calibration_rows_dependent": True,
            "targets_are_realized_reference_tails": True,
        },
    }


def predict(head, feature):
    x = np.asarray(feature, dtype=np.float64)
    if x.shape != head["mean"].shape or not np.isfinite(x).all():
        raise ValueError("Invalid deployed head input")
    z = (x - head["mean"]) / head["scale"]
    scores = z @ head["coefficients"] + head["intercept"]
    scores[head["baseline"]] = 0.
    return scores, float(np.linalg.norm(z))


def choose(head, feature, baseline=None):
    baseline = head["baseline"] if baseline is None else baseline
    if baseline != head["baseline"]:
        raise ValueError("Head baseline differs from deployment baseline")
    scores, norm = predict(head, feature)
    greedy = int(np.argmax(scores))
    margin = float(scores[greedy])
    tied = np.sum(scores == margin) > 1
    active = greedy != baseline and not tied and margin > head["threshold"]
    action = greedy if active else baseline
    return action, {
        "predicted_advantages": scores.tolist(), "greedy_action": greedy,
        "chosen_action": action, "predicted_margin": margin,
        "threshold": head["threshold"], "override": active,
        "fallback_reason": None if active else ("baseline_or_tie" if greedy == baseline or tied else "calibration_gate"),
        "standardized_norm": norm,
        "outside_fit_norm": norm > head["fit_max_standardized_norm"],
        "certificate": False,
    }


def history_feature(history, current):
    """Six H12 observations with only already-observed actions/guard/work."""
    if len(history) > 5 or len(current) != 12:
        raise ValueError("History outside six-decision horizon")
    result = np.zeros((6, 19), dtype=np.float64)
    for i, row in enumerate(history):
        if (set(row) != {"field", "action", "accepted", "scheduled_microsteps"}
                or type(row["action"]) is not int or row["action"] not in range(4)
                or type(row["accepted"]) is not bool or row["scheduled_microsteps"] != 48
                or np.asarray(row["field"]).shape != (12,) or not np.isfinite(row["field"]).all()):
            raise ValueError("Invalid observed history transaction")
        result[i, :12] = row["field"]
        result[i, 12 + row["action"]] = 1.
        result[i, 16] = float(row["accepted"])
        result[i, 17] = row["scheduled_microsteps"] / 48.
        result[i, 18] = 1.
    result[len(history), :12] = current
    result[len(history), 18] = 1.
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite history information")
    return result.reshape(-1)


def head_metadata(head):
    return {k: v for k, v in head.items() if not isinstance(v, np.ndarray)}
