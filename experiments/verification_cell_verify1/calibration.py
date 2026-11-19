"""Finite-sample split-conformal ranks, without unverified statistical guarantees.

This computes an order statistic for the event score > threshold. It does not
establish exchangeability, handle drift/adaptive selection, or bound actual
task errors. It is not a trajectory probability certificate.
"""

import math


def _finite_nonnegative(value, name):
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be numeric, excluding bool")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def split_conformal_threshold(scores, alpha):
    """Use rank ceil((n+1)*(1-alpha)); None represents +infinity safely in JSON.

    Exact integer arithmetic on alpha's binary ratio prevents rounding just
    below 1/(n+1) into an available finite threshold. Nontrivial availability
    means only that the empirical rank exists, not that assumptions hold.
    Empty calibration data returns an unavailable finite bound, never max([]).
    """
    alpha = _finite_nonnegative(alpha, "alpha")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be strictly between zero and one")
    if type(scores) not in (list, tuple):
        raise ValueError("scores must be an explicit array")
    ordered = sorted(_finite_nonnegative(score, "score") for score in scores)
    numerator, denominator = alpha.as_integer_ratio()
    rank = (
        (len(ordered) + 1) * (denominator - numerator) + denominator - 1
    ) // denominator
    available = rank <= len(ordered)
    return {
        "method": "split_conformal_rank_v1",
        "target_event": "score_exceeds_threshold",
        "alpha": alpha,
        "sample_count": len(ordered),
        "quantile_rank": rank,
        "nontrivial_bound_available": available,
        "threshold": ordered[rank - 1] if available else None,
        "exchangeability": "unverified",
        "distribution_drift": "unassessed",
        "score_coverage_guarantee": "not_established",
        "actual_error_bound": None,
    }
