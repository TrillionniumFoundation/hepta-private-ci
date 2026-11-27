"""Identifiable synthetic risk preference under fixed external utility units.

A Gaussian lottery [mean, variance] has entropic CE mean-gamma*variance/2.
Choice noise has a declared, fixed logistic temperature. Only gamma is fitted;
these choices are not evidence that a real person's preferences are known.
"""

from dataclasses import dataclass
import math

import numpy as np


class UnidentifiablePreference(ValueError):
    """The declared pair design cannot identify its scalar risk coefficient."""


def _scalar(value, name, positive=False):
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise ValueError(f"invalid {name}")
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"invalid {name}") from error
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _design(pairs, temperature):
    temperature = _scalar(temperature, "temperature", positive=True)
    pairs = np.asarray(pairs, dtype=np.float64)
    if (pairs.ndim != 3 or pairs.shape[1:] != (2, 2) or len(pairs) == 0
            or not np.isfinite(pairs).all() or np.any(pairs[:, :, 1] < 0)):
        raise ValueError("pairs must be finite [N, 2, (mean, variance)] with nonnegative variances")
    with np.errstate(over="ignore", invalid="ignore"):
        offset = (pairs[:, 0, 0] - pairs[:, 1, 0]) / temperature
        feature = -.5 * (pairs[:, 0, 1] - pairs[:, 1, 1]) / temperature
    if not np.isfinite(offset).all() or not np.isfinite(feature).all():
        raise ValueError("scaled lottery contrast is outside float64 range")
    return offset, feature


def _labels(choices, size):
    labels = np.asarray(choices)
    if labels.shape != (size,) or not np.all((labels == 0) | (labels == 1)):
        raise ValueError("one binary choice per pair is required; 1 means choose A")
    return labels.astype(np.float64)


def _logits(offset, feature, gamma):
    gamma = _scalar(gamma, "gamma")
    with np.errstate(over="ignore", invalid="ignore"):
        logits = offset + gamma * feature
    if not np.isfinite(logits).all():
        raise ValueError("choice logits are outside float64 range")
    return logits


def _sigmoid(logits):
    with np.errstate(under="ignore"):
        tail = np.exp(-np.abs(logits))
    return np.where(logits >= 0, 1 / (1 + tail), tail / (1 + tail))


def pair_choice_probabilities(pairs, gamma, temperature=1.0):
    offset, feature = _design(pairs, temperature)
    return _sigmoid(_logits(offset, feature, gamma))


def randomized_lottery_pairs(n, seed):
    """Exogenous randomized design; it has no task labels or output rewards."""
    if type(n) is not int or n <= 0:
        raise ValueError("n must be a positive integer")
    rng = np.random.default_rng(seed)
    pairs = np.empty((n, 2, 2))
    pairs[:, :, 0] = rng.normal(0, .8, size=(n, 2))
    variances = np.array([.1, .4, 1.2, 2.0])
    first = rng.integers(0, len(variances), size=n)
    second = (first + rng.integers(1, len(variances), size=n)) % len(variances)
    pairs[:, 0, 1], pairs[:, 1, 1] = variances[first], variances[second]
    pairs.flags.writeable = False
    return pairs


def simulate_choices(pairs, gamma, seed, temperature=1.0):
    """Synthetic response generator only; freeze its seed before evaluation."""
    probabilities = pair_choice_probabilities(pairs, gamma, temperature)
    choices = (np.random.default_rng(seed).random(len(probabilities)) < probabilities).astype(np.int64)
    choices.flags.writeable = False
    return choices


def _statistics(offset, feature, labels, gamma):
    logits = _logits(offset, feature, gamma)
    probabilities = _sigmoid(logits)
    with np.errstate(under="ignore", over="ignore", invalid="ignore"):
        tail = np.exp(-np.abs(logits))
        nll = np.sum(np.logaddexp(0, (1 - 2 * labels) * logits))
        score = np.sum(feature * (probabilities - labels))
        fisher = np.sum(feature ** 2 * tail / (1 + tail) ** 2)
    if not np.isfinite([nll, score, fisher]).all():
        raise ValueError("likelihood or information is outside float64 range")
    return float(nll), float(score), float(fisher)


@dataclass(frozen=True)
class PreferenceFit:
    gamma: float
    temperature: float
    bounds: tuple
    nll: float
    fisher_information: float
    standard_error: float | None
    at_boundary: bool
    train_size: int
    iterations: int


def fit_preference(pairs, choices, temperature=1.0, bounds=(0.0, 8.0)):
    """Global bounded MLE for one convex logistic negative log likelihood.

At least one nonzero variance contrast gives structural identifiability when
utility units and temperature are fixed. Small Fisher information, a boundary
fit, or poor independent predictive fit remain separate diagnostic concerns.
    """
    temperature = _scalar(temperature, "temperature", positive=True)
    offset, feature = _design(pairs, temperature)
    labels = _labels(choices, len(offset))
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise ValueError("bounds must contain two risk coefficients")
    lower, upper = (_scalar(x, "gamma bound") for x in bounds)
    if lower >= upper:
        raise ValueError("gamma bounds must be strictly ordered")
    if not np.any(feature != 0):
        raise UnidentifiablePreference("equal-variance pairs give no information about gamma")
    low_score = _statistics(offset, feature, labels, lower)[1]
    high_score = _statistics(offset, feature, labels, upper)[1]
    iterations = 0
    if low_score >= 0:
        estimate, boundary = lower, True
    elif high_score <= 0:
        estimate, boundary = upper, True
    else:
        left, right = lower, upper
        for iterations in range(1, 101):
            estimate = left + (right - left) / 2
            score = _statistics(offset, feature, labels, estimate)[1]
            if score > 0:
                right = estimate
            else:
                left = estimate
            if right - left <= 1e-12 * max(1.0, abs(estimate)):
                break
        estimate, boundary = left + (right - left) / 2, False
    nll, _, fisher = _statistics(offset, feature, labels, estimate)
    standard_error = 1 / math.sqrt(fisher) if fisher > 0 else None
    return PreferenceFit(float(estimate), temperature, (lower, upper), nll, fisher,
                         standard_error, boundary, len(labels), iterations)


def identifiability_report(pairs, gamma, temperature=1.0):
    """Design-conditional structural and local information, not a human claim."""
    offset, feature = _design(pairs, temperature)
    gamma = _scalar(gamma, "gamma")
    _, _, information = _statistics(offset, feature, np.zeros(len(offset)), gamma)
    return {"structurally_identified": bool(np.any(feature != 0)),
            "informative_pairs": int(np.count_nonzero(feature)),
            "fisher_information": information,
            "standard_error": 1 / math.sqrt(information) if information > 0 else None,
            "utility_units_fixed": True, "temperature_fixed": float(temperature),
            "real_user_identified": False}


def evaluate_preference(pairs, choices, gamma, temperature=1.0):
    """Score an already fixed coefficient on independent choices; never refit."""
    offset, feature = _design(pairs, temperature)
    labels = _labels(choices, len(offset))
    nll, score, fisher = _statistics(offset, feature, labels, gamma)
    probabilities = _sigmoid(_logits(offset, feature, gamma))
    return {"n": len(labels), "nll": nll, "mean_nll": nll / len(labels),
            "brier_score": float(np.mean((probabilities - labels) ** 2)),
            "choice_accuracy": float(np.mean((probabilities >= .5) == labels)),
            "score_at_frozen_gamma": score, "fisher_information": fisher,
            "gamma": float(gamma), "temperature": float(temperature), "refitted": False}
