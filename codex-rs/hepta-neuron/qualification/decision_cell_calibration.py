"""Fit the existing support predicate to complete decisions, not action alone.

This is an empirical pilot calibration policy, not independent calibration trust.
No feasible nonempty support means unconditional abstention. The existing strict
OOD comparison can encode that safely even when a softmax rounds to exactly one.
"""
import numpy as np

CALIBRATION_PROFILE = "hepta.decision-cell-joint-support-calibration.v1"
MAX_ROWS = 4096
MAX_ERROR = 0.05
CLASSES = {"action": 6, "target": 4, "disposition": 6, "postcondition": 6, "ood": 2}


def _scores(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values)
    if (values.ndim != 1 or not 1 <= len(values) <= MAX_ROWS or
            values.dtype.kind != "f" or not np.isfinite(values).all() or
            not ((values >= 0) & (values <= 1)).all()):
        raise ValueError("invalid bounded calibration scores")
    return values.copy()


def select_ood_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float, dict]:
    scores = _scores(scores)
    labels = np.asarray(labels)
    if (labels.shape != scores.shape or labels.dtype.kind not in "iu" or
            not np.isin(labels, (0, 1)).all() or not (labels == 0).any() or
            not (labels == 1).any()):
        raise ValueError("OOD calibration requires both labelled populations")
    inside, outside = labels == 0, labels == 1
    feasible = []
    for threshold in sorted(set([0.0, 1.0, *scores.tolist()])):
        accepted = scores < threshold
        in_accept = float(accepted[inside].mean())
        false_accept = float(accepted[outside].mean())
        if false_accept <= MAX_ERROR:
            feasible.append(((in_accept + 1 - false_accept) / 2,
                             -false_accept, in_accept, threshold))
    # Zero is always feasible: the runtime uses a strict less-than comparison.
    threshold = float(max(feasible)[3])
    accepted = scores < threshold
    return threshold, {
        "calibration_in_domain_acceptance": float(accepted[inside].mean()),
        "calibration_ood_rejection": float((~accepted[outside]).mean()),
        "calibration_ood_false_acceptance": float(accepted[outside].mean()),
    }


def select_confidence_threshold(confidence: np.ndarray, correct: np.ndarray,
                                *, eligible: np.ndarray | None = None) -> tuple[float | None, dict]:
    """Maximize nonempty supported coverage subject to the empirical error cap.

    ``None`` is an explicit infeasible result, never a permissive fallback.
    A caller must encode unconditional rejection, not substitute a threshold of
    one (which accepts probabilities that round to one).
    """
    confidence = _scores(confidence)
    correct = np.asarray(correct)
    if correct.shape != confidence.shape or correct.dtype.kind != "b":
        raise ValueError("calibration correctness must be aligned booleans")
    if eligible is None:
        eligible = np.ones(confidence.shape, dtype=bool)
    eligible = np.asarray(eligible)
    if eligible.shape != confidence.shape or eligible.dtype.kind != "b":
        raise ValueError("calibration eligibility must be aligned booleans")
    feasible = []
    for threshold in sorted(set([0.0, 1.0, *confidence.tolist()])):
        accepted = eligible & (confidence >= threshold)
        if not accepted.any():
            continue
        error = float((~correct[accepted]).mean())
        if error <= MAX_ERROR:
            feasible.append((int(accepted.sum()), -error, threshold))
    threshold = float(max(feasible)[2]) if feasible else None
    accepted = (eligible & (confidence >= threshold) if threshold is not None
                else np.zeros(confidence.shape, dtype=bool))
    return threshold, {
        "calibration_confidence_coverage": float(accepted.mean()),
        "calibration_confidence_error": float((~correct[accepted]).mean()) if accepted.any() else None,
    }


def joint_support_calibration(probabilities: dict, labels: dict) -> dict:
    """Fit support using action, applicable target, disposition and postcondition.

    OOD acceptance is fixed first. Confidence selection evaluates that exact
    intersection; every accepted OOD row is an error, even with matching labels.
    Only the supplied calibration partition is inspected. Returned scalar
    thresholds retain their existing runtime meaning and require no wire change.
    """
    if set(probabilities) != set(CLASSES) or set(labels) != set(CLASSES):
        raise ValueError("incomplete calibration heads")
    p, y = {}, {}
    count = None
    for name, classes in CLASSES.items():
        values, expected = np.asarray(probabilities[name]), np.asarray(labels[name])
        if (values.ndim != 2 or values.shape[1] != classes or
                not 1 <= len(values) <= MAX_ROWS or values.dtype.kind != "f" or
                not np.isfinite(values).all() or not ((values >= 0) & (values <= 1)).all() or
                not np.allclose(values.sum(axis=1), 1, rtol=0, atol=1e-5)):
            raise ValueError("invalid calibrated probability matrix")
        count = len(values) if count is None else count
        lower = -1 if name == "target" else 0
        if (len(values) != count or expected.shape != (count,) or expected.dtype.kind not in "iu" or
                not ((expected >= lower) & (expected < classes)).all()):
            raise ValueError("invalid calibration labels")
        p[name], y[name] = values.copy(), expected.copy()
    inside = y["ood"] == 0
    correct = inside.copy()
    for name in ("action", "target", "disposition", "postcondition"):
        matches = p[name].argmax(axis=1) == y[name]
        if name == "target":
            matches |= y[name] < 0
        correct &= matches
    ood_threshold, _ = select_ood_threshold(p["ood"][:, 1], y["ood"])
    confidence = p["action"].max(axis=1)
    threshold, _ = select_confidence_threshold(
        confidence, correct, eligible=p["ood"][:, 1] < ood_threshold)
    feasible = threshold is not None
    if not feasible:
        threshold, ood_threshold = 1.0, 0.0
    confidence_accepted = confidence >= threshold
    ood_accepted = p["ood"][:, 1] < ood_threshold
    supported = confidence_accepted & ood_accepted
    errors = int((supported & ~correct).sum())
    return {
        "calibration_profile": CALIBRATION_PROFILE,
        "minimum_confidence": threshold, "maximum_ood_probability": ood_threshold,
        "calibration_support_feasible": feasible,
        "calibration_support_mode": "empirical_joint_support" if feasible else "reject_all",
        "calibration_supported_rows": int(supported.sum()),
        "calibration_supported_coverage": float(supported.mean()),
        "calibration_supported_joint_errors": errors,
        "calibration_supported_joint_error": errors / int(supported.sum()) if supported.any() else None,
        # Keep these historical marginal diagnostics' meanings unchanged.
        "calibration_confidence_coverage": float(confidence_accepted.mean()),
        "calibration_confidence_error": float((p["action"].argmax(axis=1)[confidence_accepted] !=
                                               y["action"][confidence_accepted]).mean()) if confidence_accepted.any() else None,
        "calibration_in_domain_acceptance": float(ood_accepted[inside].mean()),
        "calibration_ood_rejection": float((~ood_accepted[~inside]).mean()),
        "calibration_ood_false_acceptance": float(ood_accepted[~inside].mean()),
    }
