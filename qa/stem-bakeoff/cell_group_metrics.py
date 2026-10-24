"""Action metrics with one total weight per independent bug group."""

import numpy as np


THRESHOLDS = (0., .5, .6, .7, .8, .9, .95, 1.)


def independent_group_weights(rows, multiplicities=None):
    groups = {}
    for index, row in enumerate(rows):
        if type(row.get("group_id")) is not str or not row["group_id"]:
            raise ValueError("explicit bug-group IDs required")
        groups.setdefault(row["group_id"], []).append(index)
    if not groups:
        raise ValueError("nonempty action rows required")
    counts = {group: 1 for group in groups} if multiplicities is None else dict(multiplicities)
    if set(counts) != set(groups) or any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError("one nonnegative integer bootstrap count per source group required")
    weights = np.empty(len(rows), dtype=np.float64)
    for group, indices in groups.items():
        weights[indices] = counts[group]/len(indices)
    if not weights.sum() > 0:
        raise ValueError("positive effective group mass required")
    return weights, groups


def _recalls(predicted, labels, weights, accepted=None):
    recalls = []
    for label in (0, 1):
        mask = labels == label
        support = float(weights[mask].sum())
        correct = mask & (predicted == label)
        if accepted is not None:
            correct &= accepted
        recalls.append(float(weights[correct].sum()/support) if support else None)
    return recalls


def weighted_auc(scores, labels, weights):
    positive, negative = float(weights[labels == 1].sum()), float(weights[labels == 0].sum())
    if positive == 0 or negative == 0:
        return None
    order = np.argsort(scores, kind="stable")
    _, starts = np.unique(scores[order], return_index=True)
    positives = np.add.reduceat(weights[order]*(labels[order] == 1), starts)
    negatives = np.add.reduceat(weights[order]*(labels[order] == 0), starts)
    return float(np.sum(positives*(np.cumsum(negatives)-.5*negatives))/(positive*negative))


def group_weighted_metrics(probabilities, labels, rows, *, threshold=.7, eligible=None,
                           calibration_prior=.5, group_multiplicities=None):
    p, y = np.asarray(probabilities, dtype=np.float64), np.asarray(labels)
    if (p.ndim != 2 or p.shape != (len(y), 2) or not 1 <= len(y) <= 16384
            or y.dtype.kind not in "iu" or np.any((y < 0) | (y > 1)) or len(rows) != len(y)
            or not np.isfinite(p).all() or np.any((p < 0) | (p > 1))
            or not np.allclose(p.sum(axis=1), 1, atol=1e-12, rtol=0)
            or not 0 <= threshold <= 1 or not 0 < calibration_prior < 1):
        raise ValueError("finite binary probabilities/labels and explicit action rows required")
    admission = np.ones(len(y), dtype=bool) if eligible is None else np.asarray(eligible)
    if admission.dtype != np.bool_ or admission.shape != y.shape:
        raise ValueError("boolean eligibility per action required")
    weights, groups = independent_group_weights(rows, group_multiplicities)
    mass = float(weights.sum())
    mean = lambda values: float(np.dot(weights, values)/mass)
    predicted, confidence = p.argmax(axis=1), p.max(axis=1)
    correct = predicted == y
    accepted = admission & (confidence >= threshold)
    recalls, successful_recalls = (_recalls(predicted, y, weights, mask) for mask in (None, accepted))
    support = [float(weights[y == k].sum()) for k in (0, 1)]
    balanced = lambda values: float(np.mean(values)) if all(v is not None for v in values) else None
    confusion, selective = np.zeros((2, 2)), np.zeros((2, 3))
    np.add.at(confusion, (y, predicted), weights)
    np.add.at(selective, (y, np.where(accepted, predicted, 2)), weights)
    accepted_mass = float(weights[accepted].sum())
    accuracy = float(weights[accepted & correct].sum()/accepted_mass) if accepted_mass else None
    ece, bins = 0., np.minimum((confidence*10).astype(int), 9)
    for index in range(10):
        mask = bins == index
        amount = float(weights[mask].sum())
        if amount:
            ece += abs(float(weights[mask]@(confidence[mask]-correct[mask])))/mass
    curve = []
    for cutoff in THRESHOLDS:
        mask = admission & (confidence >= cutoff)
        amount = float(weights[mask].sum())
        curve.append({"threshold": cutoff, "accepted_rows": int(mask.sum()), "accepted_group_mass": amount,
            "coverage": amount/mass, "risk": float(weights[mask & ~correct].sum()/amount) if amount else None,
            "overall_success": mean(mask & correct)})
    prior_recalls = _recalls(p[:, 1] > calibration_prior+1e-12, y, weights)
    return {"rows": len(y), "groups": len(groups), "effective_group_mass": mass,
        "weighting": "each bug total1; bootstrap multiplies whole bug mass; class recalls normalize weighted class mass",
        "scope": "available labelled actions only; all-proposal and infrastructure denominators reported separately",
        "class_support": np.bincount(y, minlength=2).tolist(), "weighted_class_support": support,
        "forced_accuracy": mean(correct), "balanced_accuracy": balanced(recalls),
        "balanced_accuracy_status": "available" if all(support) else "unavailable_missing_class",
        "per_class_recall": recalls, "positive_recall": recalls[1],
        "nll": mean(-np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1))),
        "brier_multiclass_sum": mean(np.square(p-np.eye(2)[y]).sum(axis=1)),
        "ece10_equal_width": ece, "confusion_matrix": confusion.tolist(),
        "threshold": threshold, "accepted": int(accepted.sum()), "abstained": int((~accepted).sum()),
        "accepted_group_mass": accepted_mass, "coverage": accepted_mass/mass,
        "selective_accuracy": accuracy, "selective_risk": 1-accuracy if accuracy is not None else None,
        "overall_success": mean(accepted & correct), "balanced_success": balanced(successful_recalls),
        "confusion_with_abstention_last_column": selective.tolist(), "risk_coverage": curve,
        "auroc": weighted_auc(p[:, 1], y, weights), "calibration_prior_threshold": calibration_prior,
        "balanced_accuracy_at_prior_threshold": balanced(prior_recalls),
        "positive_recall_at_prior_threshold": prior_recalls[1], "nll_probability_floor": 1e-15}
