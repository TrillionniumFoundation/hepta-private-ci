"""One explicit terminal conditional-law schema and separate Q24 release law."""

import math
from functools import lru_cache

import numpy as np
from scipy.special import logsumexp

from ..analytic import event_log_probs


SCHEMA = "hepta.conditional-law.v4"
Q24 = 1 << 24


def validate_law(law):
    if set(law) != {"schema", "weights", "means", "variances", "semantics"} or law["schema"] != SCHEMA or law["semantics"] != "terminal":
        raise ValueError("Explicit terminal conditional-law schema required")
    w, m, v = [np.asarray(law[k], dtype=float) for k in ("weights", "means", "variances")]
    if (w.ndim != 1 or not 1 <= len(w) <= 2 or m.shape != w.shape or v.shape != w.shape
            or not all(np.isfinite(x).all() for x in (w, m, v)) or np.any(w <= 0)
            or np.any(v <= 0) or abs(float(w.sum()) - 1) > 1e-12):
        raise ValueError("One or two finite positive Gaussian components required")
    return w / w.sum(), m, v


def make_law(weights, means, variances):
    law = {"schema": SCHEMA, "weights": list(map(float, weights)),
           "means": list(map(float, means)), "variances": list(map(float, variances)), "semantics": "terminal"}
    validate_law(law)
    return law


def event_logs(law, lower, upper):
    """Physical terminal logs; no floor, moment collapse, or first-hit semantics."""
    w, m, v = validate_law(law)
    if not math.isfinite(lower) or not math.isfinite(upper) or not lower < upper:
        raise ValueError("Finite strictly ordered boundaries required")
    return logsumexp(np.log(w)[:, None] + event_log_probs(m, v, lower, upper), axis=0)


def log_density(law, value):
    w, m, v = validate_law(law)
    value = np.asarray(value, dtype=float)
    if not np.isfinite(value).all():
        raise ValueError("Finite density argument required")
    return logsumexp(np.log(w) - .5 * (np.log(2 * np.pi * v) + (value[..., None] - m) ** 2 / v), axis=-1)


def cdf(law, value):
    from scipy.special import ndtr
    w, m, v = validate_law(law)
    return np.sum(w * ndtr((np.asarray(value)[..., None] - m) / np.sqrt(v)), axis=-1)


def positive_q24(probabilities):
    """Uniform contamination K/Q plus Hamilton rounding; not physical tails.

    Every released count is positive, the sum is Q, and component absolute
    error from normalized p is strictly below K/Q (FP normalization aside).
    This operation is only used for full-support Gaussian categories/weights.
    """
    p = np.asarray(probabilities, dtype=float)
    if (p.ndim != 1 or not 1 <= len(p) <= 3 or not np.isfinite(p).all()
            or np.any(p < 0) or abs(float(p.sum()) - 1) > 1e-12):
        raise ValueError("Normalized finite categorical probabilities required")
    p = p / p.sum()
    raw = (Q24 - len(p)) * p
    counts = 1 + np.floor(raw).astype(np.int64)
    order = np.argsort(-(raw - np.floor(raw)), kind="stable")
    counts[order[:Q24 - int(counts.sum())]] += 1
    return counts.tolist()


def release_law(law, lower, upper):
    logs = event_logs(law, lower, upper)
    probabilities = np.exp(logs)
    counts = positive_q24(probabilities)
    w, m, v = validate_law(law)
    mean = float(w @ m)
    variance = float(w @ (v + (m - mean) ** 2))
    return {"conditional_law": law, "lower": float(lower), "upper": float(upper),
            "physical_log_probabilities": logs.tolist(), "physical_probabilities": probabilities.tolist(),
            "probabilities_q24": counts, "probabilities": [c / Q24 for c in counts],
            "mean": mean, "variance": variance, "release_schema": "positive-hamilton-q24.v1",
            "maximum_coordinate_absolute_error": len(counts) / Q24,
            "maximum_released_event_nll": math.log(Q24)}


def posterior(prior, residuals, variances, noise_scale=1.0):
    """Exact Gaussian-mixture Bayesian update on acquired observations only."""
    w, m, v = validate_law(prior)
    y, r = np.asarray(residuals, dtype=float), np.asarray(variances, dtype=float) * noise_scale
    if (y.ndim != 1 or not 1 <= len(y) <= 2 or y.shape != r.shape
            or not np.isfinite(y).all() or not np.isfinite(r).all() or np.any(r <= 0)):
        raise ValueError("One or two acquired finite independent sensors required")
    logw = np.log(w)
    for observation, noise in zip(y, r):
        predictive = v + noise
        logw -= .5 * (np.log(2 * np.pi * predictive) + (observation - m) ** 2 / predictive)
        gain = v / predictive
        m, v = m + gain * (observation - m), v * (1 - gain)
    weights = np.exp(logw - logsumexp(logw))
    # Valid prior/sensor bounds in this study keep component weights representable.
    return make_law(weights, m, v)


@lru_cache(maxsize=3)
def _hermite(nodes):
    return np.polynomial.hermite.hermgauss(nodes)


def action_values(law, public, noise_scale, nodes=64):
    """Finite-horizon mixture continuation integral; GH approximation is named."""
    w, m, v = validate_law(law)
    mean = float(w @ m)
    amount = round(mean * Q24) / Q24
    repair = 2 * amount * mean - amount * amount - public["repair_cost"]
    wait = None
    if len(public["residuals"]) == 1:
        points, weights = _hermite(nodes)
        noise = noise_scale * public["wait_variance"]
        observations = (m[:, None] + np.sqrt(2 * (v + noise))[:, None] * points).reshape(-1)
        predictive_variance = v + noise
        logweights = (np.log(w)[None, :] - .5 * (np.log(2 * np.pi * predictive_variance)[None, :]
                      + (observations[:, None] - m[None, :]) ** 2 / predictive_variance[None, :]))
        conditional_weights = np.exp(logweights - logsumexp(logweights, axis=1)[:, None])
        conditional_means = m[None, :] + v[None, :] / predictive_variance[None, :] * (observations[:, None] - m[None, :])
        future_mean = np.sum(conditional_weights * conditional_means, axis=1)
        payoff = np.maximum(future_mean ** 2 - public["repair_cost"], 0).reshape(len(w), nodes)
        wait = float(w @ (payoff @ weights / math.sqrt(math.pi))) - public["wait_cost"]
    return {"repair_amount": amount, "repair_gain": repair, "wait_gain": wait,
            "continuation_rule": f"gauss-hermite-{nodes}-continuous-optimal-repair"}
