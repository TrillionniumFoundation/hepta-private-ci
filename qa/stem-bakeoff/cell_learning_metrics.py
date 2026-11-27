"""All-denominator task scores for frozen Cell predictions.

Abstention is not a correct answer. Probability scores cover every example;
selective scores separately describe the accepted subset. These are empirical
scores, not guarantees of calibration or future task quality.
"""

import numpy as np


def probabilities(logits, temperature=1.0):
    values = np.asarray(logits, dtype=np.float64)
    if (values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 2
            or not np.isfinite(values).all() or type(temperature) not in (float, int)
            or not np.isfinite(temperature) or temperature <= 0):
        raise ValueError("finite logits and positive temperature required")
    values = values / temperature
    values -= values.max(axis=1, keepdims=True)
    weights = np.exp(values)
    return weights / weights.sum(axis=1, keepdims=True)


def task_metrics(probability, labels, *, threshold=0.7, eligible=None):
    """Return forced, abstention-aware and per-class metrics without dropping rows."""
    p = np.asarray(probability, dtype=np.float64)
    y = np.asarray(labels)
    if (p.ndim != 2 or len(p) < 1 or p.shape[1] < 2 or y.shape != (len(p),)
            or y.dtype.kind not in "iu" or not np.isfinite(p).all()
            or np.any(p < 0) or np.any(p > 1)
            or not np.allclose(p.sum(axis=1), 1, atol=1e-8, rtol=1e-8)
            or np.any(y >= p.shape[1]) or np.any(y < 0)
            or type(threshold) not in (float, int) or not np.isfinite(threshold)
            or not 0 <= threshold <= 1):
        raise ValueError("invalid probability, label or threshold inputs")
    admission = np.ones(len(p), dtype=bool) if eligible is None else np.asarray(eligible)
    if admission.dtype != np.bool_ or admission.shape != (len(p),):
        raise ValueError("eligibility must be a boolean vector")
    predicted = p.argmax(axis=1)
    confidence = p.max(axis=1)
    correct = predicted == y
    accepted = admission & (confidence >= threshold)
    classes = p.shape[1]
    confusion = np.zeros((classes, classes), dtype=np.int64)
    np.add.at(confusion, (y, predicted), 1)
    selective_confusion = np.zeros((classes, classes + 1), dtype=np.int64)
    np.add.at(selective_confusion, (y, np.where(accepted, predicted, classes)), 1)
    supports = np.bincount(y, minlength=classes)
    recalls = [float(confusion[k, k] / supports[k]) if supports[k] else None
               for k in range(classes)]
    effective_recalls = [float(selective_confusion[k, k] / supports[k])
                         if supports[k] else None for k in range(classes)]
    ece = 0.0
    bins = np.minimum((confidence * 10).astype(int), 9)
    for b in range(10):
        mask = bins == b
        if mask.any():
            ece += float(mask.mean() * abs(confidence[mask].mean() - correct[mask].mean()))
    curve = []
    for cutoff in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0):
        mask = admission & (confidence >= cutoff)
        curve.append({"threshold": cutoff, "accepted": int(mask.sum()),
                      "coverage": float(mask.mean()),
                      "risk": float((~correct[mask]).mean()) if mask.any() else None,
                      "overall_success": float((correct & mask).mean())})
    one_hot = np.eye(classes)[y]
    return {"rows": len(y), "classes": classes, "class_support": supports.tolist(),
            "forced_accuracy": float(correct.mean()),
            "balanced_accuracy": float(np.mean([r for r in recalls if r is not None])),
            "per_class_recall": recalls, "positive_recall": recalls[1] if classes == 2 else None,
            "confusion_matrix": confusion.tolist(),
            "nll": float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1)).mean()),
            "brier_multiclass_sum": float(np.square(p - one_hot).sum(axis=1).mean()),
            "ece10_equal_width": ece, "threshold": threshold,
            "accepted": int(accepted.sum()), "abstained": int((~accepted).sum()),
            "coverage": float(accepted.mean()),
            "selective_accuracy": float(correct[accepted].mean()) if accepted.any() else None,
            "selective_risk": float((~correct[accepted]).mean()) if accepted.any() else None,
            "overall_success": float((correct & accepted).mean()),
            "balanced_success": float(np.mean([r for r in effective_recalls if r is not None])),
            "confusion_with_abstention_last_column": selective_confusion.tolist(),
            "risk_coverage": curve}


def calibrate_temperature(logits, labels, grid=(0.5, 1.0, 2.0, 4.0, 8.0)):
    """Fit temperature on an explicitly separate calibration cohort only."""
    if not isinstance(grid, (tuple, list)) or not grid:
        raise ValueError("nonempty temperature grid required")
    candidates = []
    for temperature in grid:
        p = probabilities(logits, temperature)
        score = task_metrics(p, labels)["nll"]
        candidates.append((score, abs(np.log(temperature)), temperature))
    best = min(candidates)
    return float(best[2]), {"nll": float(best[0]), "grid": list(grid),
                            "boundary_selected": best[2] in (min(grid), max(grid))}
