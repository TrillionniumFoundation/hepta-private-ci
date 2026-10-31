"""Separate protected projections for Q24 Gaussian parameters and event mass.

The frozen same-public-information anchor is an explicit extra reference.
These guards do not change or inherit the original native owner's guarantees.
"""

from decimal import Decimal, ROUND_CEILING, localcontext
import math

import numpy as np
from scipy.special import logsumexp


Q24 = 1 << 24


def _epsilon(epsilon):
    if not np.isscalar(epsilon) or not np.isfinite(epsilon) or not 0 <= epsilon <= 0.02:
        raise ValueError("Protected Q24 qualification requires epsilon in [0,0.02]")
    return float(epsilon)


def guard_quantized(anchor_mean, anchor_variance, proposal_mean, epsilon=0.02):
    """Return Q24-grid (mean,variance,certificate) with a Gaussian NLL envelope.

    Arrays broadcast. The proposal may be an event-decoded mean. The anchor is
    separately declared and must use the same public information. Half the
    logscore budget is reserved before quantization; the delivered parameters
    are checked afterwards. No returned candidate may exceed the budget.
    """
    epsilon = _epsilon(epsilon)
    m0, v0, proposal = np.broadcast_arrays(np.asarray(anchor_mean, dtype=float),
                                         np.asarray(anchor_variance, dtype=float),
                                         np.asarray(proposal_mean, dtype=float))
    if (not all(np.isfinite(x).all() for x in (m0, v0, proposal)) or np.any(np.abs(m0) > 1e4)
            or np.any(v0 < 1e-4) or np.any(v0 > 100)):
        raise ValueError("Q24 guard domain requires |anchor mean|<=1e4, variance in [1e-4,100], finite proposal")
    standard = np.sqrt(v0)
    change = np.clip(proposal - m0, -0.5 * epsilon * standard, 0.5 * epsilon * standard)
    mean_q24 = np.rint((m0 + change) * Q24).astype(np.int64)
    mean = mean_q24.astype(float) / Q24
    d = (mean - m0) / standard
    variance_q24 = np.maximum(np.ceil(v0 * (1.0 + np.abs(d)) * Q24), np.ceil(v0 * Q24)).astype(np.int64)
    variance = variance_q24.astype(float) / Q24
    # Subtract first to avoid rounding c to one before forming c-1.
    excess = (variance - v0) / v0
    equal = (excess == 0) & (d == 0)
    valid = (excess > 0) | equal
    if not np.all(valid):
        raise ValueError("Quantized Gaussian cannot satisfy a finite pointwise envelope")
    penalty = np.divide(d * d, 2.0 * excess, out=np.zeros_like(d), where=excess > 0)
    bound = 0.5 * np.log1p(excess) + penalty
    if not np.isfinite(bound).all() or np.any(bound > epsilon):
        raise ValueError("Quantized Gaussian exceeds the registered pointwise NLL budget")
    native_domain = (np.abs(mean) <= 8) & (variance <= 8) & (variance >= 1.0 / Q24)
    certificate = {
        "schema": "hepta.protected-q24.gaussian.v1", "epsilon": epsilon,
        "mean_q24": mean_q24, "variance_q24": variance_q24,
        "normalized_correction": d, "relative_variance_inflation": excess,
        "pointwise_nll_bound": bound, "margin": epsilon - bound,
        "protected_mask": valid & (bound <= epsilon), "native_typed_domain_mask": native_domain,
        "anchor_required": True, "additional_same_public_information_reference": True,
        "input_rounding": "mean nearest ties-even; variance ceiling; outputs exactly on Q24 grid",
        "scope": "Gaussian density logscore relative to declared anchor, not rounded categorical event logscore",
    }
    return mean, variance, certificate


def _json_safe(value):
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def guard_quantized_scalar(anchor_mean, anchor_variance, proposal_mean, epsilon=0.02):
    mean, variance, certificate = guard_quantized(anchor_mean, anchor_variance, proposal_mean, epsilon)
    if mean.ndim != 0:
        raise ValueError("Scalar runtime projection requires scalar inputs")
    return _json_safe({"mean": mean, "variance": variance, **certificate})


def _project_integer_simplex(target, minimum, total):
    """Euclidean integer projection onto sum(q)=total and q>=integer minima."""
    target = np.asarray(target, dtype=float)
    minimum = np.asarray(minimum, dtype=np.int64)
    if target.shape != minimum.shape or target.ndim != 2 or target.shape[1] != 3:
        raise ValueError("Expected rows of three target/minimum counts")
    if not np.isfinite(target).all() or np.any(minimum < 0) or np.any(minimum.sum(1) > total):
        raise ValueError("Invalid integer simplex projection")
    free = np.ones(target.shape, dtype=bool)
    for _ in range(3):
        free_count = free.sum(1)
        shift = np.divide(np.sum(np.where(free, target, minimum), axis=1) - total,
                          free_count, out=np.zeros(len(target)), where=free_count > 0)
        projected = np.where(free, target - shift[:, None], minimum)
        violated = free & (projected < minimum)
        if not np.any(violated):
            break
        free &= ~violated
    counts = np.maximum(np.floor(projected).astype(np.int64), minimum)
    remaining = total - counts.sum(1)
    if np.any(np.abs(remaining) > 3):
        raise ValueError("Continuous simplex projection failed numerical accounting")
    rows = np.arange(len(counts))
    # Integer marginal costs give the optimal rounding; argmin resolves ties by channel.
    for _ in range(3):
        add = remaining > 0
        marginal = 2.0 * (counts - target) + 1.0
        choice = np.argmin(marginal, axis=1)
        counts[rows[add], choice[add]] += 1
        remaining[add] -= 1
        subtract = remaining < 0
        marginal = np.where(counts > minimum, -2.0 * (counts - target) + 1.0, np.inf)
        choice = np.argmin(marginal, axis=1)
        counts[rows[subtract], choice[subtract]] -= 1
        remaining[subtract] += 1
    if np.any(remaining != 0) or np.any(counts < minimum):
        raise ValueError("Integer mass allocation failed")
    return counts


def protected_event_quantize(anchor_logp, candidate_probs, epsilon=0.02):
    """Project after native Q24 output, protecting each anchored event logscore.

    Return (integer counts, certificate); final axis is put/neutral/call.
    Finite anchor logs retain at least one unit even if exp(logp) underflows.
    The minimum calculation uses 80-digit decimal exp with upward enclosure.
    """
    epsilon = _epsilon(epsilon)
    anchor, candidate = np.broadcast_arrays(np.asarray(anchor_logp, dtype=float),
                                            np.asarray(candidate_probs, dtype=float))
    if anchor.ndim < 1 or anchor.shape[-1] != 3:
        raise ValueError("Protected event projection requires a final three-event axis")
    if (np.isnan(anchor).any() or np.isposinf(anchor).any() or not np.isfinite(candidate).all()
            or np.any(candidate < 0) or np.any(np.abs(candidate.sum(-1) - 1.0) > 1e-10)
            or np.any(np.abs(logsumexp(anchor, axis=-1)) > 1e-10)):
        raise ValueError("Expected normalized anchor logs and finite normalized candidate probabilities")
    shape = anchor.shape
    logs, probabilities = anchor.reshape(-1, 3), candidate.reshape(-1, 3)
    probabilities = probabilities / probabilities.sum(1, keepdims=True)
    minimum = np.zeros(logs.shape, dtype=np.int64)
    with localcontext() as context:
        context.prec = 80
        budget, mass = Decimal.from_float(epsilon), Decimal(Q24)
        for row, channel in np.ndindex(logs.shape):
            value = float(logs[row, channel])
            if value == -math.inf:
                continue
            if value < -32:
                minimum[row, channel] = 1
                continue
            exponent = Decimal.from_float(value) - budget
            probability = exponent.exp()
            upper = probability if exponent == 0 else probability.next_plus()
            minimum[row, channel] = max(1, int((mass * upper).to_integral_value(rounding=ROUND_CEILING)))
    if np.any(minimum.sum(1) > Q24):
        raise ValueError("No Q24 event distribution satisfies the requested logscore budget")
    counts = _project_integer_simplex(probabilities * Q24, minimum, Q24)
    with np.errstate(divide="ignore", invalid="ignore"):
        delivered_logp = np.log(counts.astype(float)) - math.log(Q24)
        excess = np.where(np.isfinite(logs), logs - delivered_logp, -np.inf)
    maximum = excess.max(1)
    supported = np.all((counts > 0) | ~np.isfinite(logs), axis=1)
    if not supported.all() or np.any(maximum > epsilon):
        raise ValueError("Delivered categorical Q24 distribution violates its pointwise logscore budget")
    certificate = {
        "schema": "hepta.protected-q24.events.v1", "epsilon": epsilon, "mass": Q24,
        "minimum_counts": minimum.reshape(shape), "pointwise_event_nll_bound": excess.reshape(shape),
        "maximum_event_nll_excess": maximum.reshape(shape[:-1]),
        "margin": (epsilon - maximum).reshape(shape[:-1]),
        "exact_mass": (counts.sum(1) == Q24).reshape(shape[:-1]),
        "positive_anchor_supported": supported.reshape(shape[:-1]),
        "projection_squared_error": np.sum((counts / Q24 - probabilities)**2, axis=1).reshape(shape[:-1]),
        "zero_anchor_event": np.isneginf(anchor), "additional_anchor_reference": True,
        "original_native_owner_output_unchanged": True,
        "scope": "Separate post-native adapter projection; requires its own durable binding",
    }
    return counts.reshape(shape), certificate


def protected_event_quantize_scalar(anchor_logp, candidate_probs, epsilon=0.02):
    counts, certificate = protected_event_quantize(anchor_logp, candidate_probs, epsilon)
    if counts.ndim != 1:
        raise ValueError("Scalar runtime event projection requires one three-event vector")
    return _json_safe({"counts": counts, **certificate})
