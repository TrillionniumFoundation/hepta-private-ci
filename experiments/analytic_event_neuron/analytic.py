"""Gaussian terminal-event operators; no implicit firing or policy semantics.

Channels are (put, neutral, call): X <= lower, lower < X <= upper, X > upper.
The zero-variance convention is exact, including atoms at either threshold.
Finite-horizon Gaussian predictions concern terminal states, not first passage.
"""

import numpy as np
from scipy.special import erf, log_ndtr


_LOG_SQRT_2PI = 0.5 * np.log(2.0 * np.pi)


def _arguments(mean, variance, lower, upper):
    arrays = np.broadcast_arrays(*[
        np.asarray(x, dtype=np.float64) for x in (mean, variance, lower, upper)
    ])
    m, v, lo, hi = arrays
    if (not np.isfinite(m).all() or not np.isfinite(v).all()
            or np.any(v < 0) or np.isnan(lo).any() or np.isnan(hi).any()
            or np.any(lo > hi)):
        raise ValueError("Finite mean, finite nonnegative variance and ordered bounds required")
    return arrays


def _log_interval_standard(a, b):
    """Log integral of the standard normal density on (a,b].

    Same-tail subtraction uses log-CDF/log-survival and expm1. Intervals
    straddling zero use erf addition. For |midpoint|*width <= 1e-3, a local
    even Taylor integral avoids cancellation of nearly equal log-CDF values.
    Its first omitted term is O((1+|midpoint|)^6*width^6).
    """
    a, b = np.broadcast_arrays(a, b)
    answer = np.full(a.shape, -np.inf, dtype=np.float64)
    active = a < b
    left = active & (b <= 0)
    right = active & (a >= 0)
    for mask, big, small in (
        (left, log_ndtr(b[left]), log_ndtr(a[left])),
        (right, log_ndtr(-a[right]), log_ndtr(-b[right])),
    ):
        with np.errstate(divide="ignore", invalid="ignore"):
            answer[mask] = big + np.log(-np.expm1(small - big))
    middle = active & ~left & ~right
    answer[middle] = np.log(0.5 * (
        erf(b[middle] / np.sqrt(2.0)) - erf(a[middle] / np.sqrt(2.0))
    ))
    finite = active & np.isfinite(a) & np.isfinite(b)
    width = np.zeros(a.shape)
    midpoint = np.zeros(a.shape)
    width[finite] = b[finite] - a[finite]
    midpoint[finite] = a[finite] + 0.5 * width[finite]
    narrow = finite & (width * (1.0 + np.abs(midpoint)) <= 1e-3)
    w, m = width[narrow], midpoint[narrow]
    m2 = m * m
    correction = (m2 - 1.0) * w**2 / 24.0
    correction += (m2*m2 - 6.0*m2 + 3.0) * w**4 / 1920.0
    answer[narrow] = -0.5*m2 - _LOG_SQRT_2PI + np.log(w) + np.log1p(correction)
    return answer


def event_log_probs(mean, variance, lower, upper):
    """Return broadcast (...,3) terminal-event log probabilities.

    Bounds may be infinite. Degenerate or empty events have log mass -inf.
    No epsilon floor is applied, so an impossible observed event remains
    impossible and finite far-tail log likelihoods are retained.
    """
    m, v, lo, hi = _arguments(mean, variance, lower, upper)
    scale = np.sqrt(np.where(v > 0, v, 1.0))
    with np.errstate(over="ignore"):
        a, b = (lo-m)/scale, (hi-m)/scale
    logs = np.stack((log_ndtr(a), _log_interval_standard(a, b), log_ndtr(-b)), axis=-1)
    zero = v == 0
    deterministic = np.stack((m <= lo, (m > lo) & (m <= hi), m > hi), axis=-1)
    return np.where(zero[..., None], np.where(deterministic, 0.0, -np.inf), logs)


def event_probs(mean, variance, lower, upper):
    """Return probabilities in put/neutral/call order, without fake floors."""
    return np.exp(event_log_probs(mean, variance, lower, upper))


def event_gradients(mean, variance, lower, upper):
    """Analytic mean/variance derivatives, defined only at positive variance."""
    m, v, lo, hi = _arguments(mean, variance, lower, upper)
    if np.any(v <= 0):
        raise ValueError("A zero-variance step has no ordinary smooth probability gradient")
    scale = np.sqrt(v)
    with np.errstate(over="ignore"):
        a, b = (lo-m)/scale, (hi-m)/scale
        pa, pb = np.exp(-0.5*a*a-_LOG_SQRT_2PI), np.exp(-0.5*b*b-_LOG_SQRT_2PI)
    apa = np.zeros(a.shape)
    bpb = np.zeros(b.shape)
    np.multiply(a, pa, out=apa, where=np.isfinite(a))
    np.multiply(b, pb, out=bpb, where=np.isfinite(b))
    mean_grad = np.stack((-pa, pa-pb, pb), axis=-1)/scale[..., None]
    var_grad = np.stack((-apa, apa-bpb, bpb), axis=-1)/(2.0*v[..., None])
    if not (np.isfinite(mean_grad).all() and np.isfinite(var_grad).all()):
        raise ValueError("Probability gradient exceeds the declared FP64 range")
    return {"mean": mean_grad, "variance": var_grad}


def gaussian_transition(mean, variance, drift, diffusion, dt):
    """Exact affine Gaussian prediction under constant drift and diffusion.

    diffusion is sigma, measured per square-root time. Independent process
    noise is assumed; variance is the uncertainty of the current latent state.
    State-dependent coefficients evaluated at the current mean would instead
    define a frozen-coefficient approximation and are not certified here.
    """
    m, v, b, sigma, time = np.broadcast_arrays(*[
        np.asarray(x, dtype=np.float64) for x in (mean, variance, drift, diffusion, dt)
    ])
    if (not all(np.isfinite(x).all() for x in (m, v, b, sigma, time))
            or np.any(v < 0) or np.any(sigma < 0) or np.any(time < 0)):
        raise ValueError("Finite inputs, nonnegative variance/diffusion/time required")
    with np.errstate(over="ignore"):
        predicted_mean = m+b*time
        predicted_variance = v+sigma*sigma*time
    if not (np.isfinite(predicted_mean).all() and np.isfinite(predicted_variance).all()):
        raise ValueError("Gaussian prediction exceeds the declared FP64 range")
    return predicted_mean, predicted_variance


def transition_event_gradients(mean, variance, drift, diffusion, dt, lower, upper):
    """Chain rule with drift independent of diffusion (not the coupled BS drift)."""
    m, v = gaussian_transition(mean, variance, drift, diffusion, dt)
    grad = event_gradients(m, v, lower, upper)
    b, sigma, time = np.broadcast_arrays(
        np.asarray(drift, dtype=float), np.asarray(diffusion, dtype=float), np.asarray(dt, dtype=float)
    )
    return {**grad, "drift": grad["mean"]*time[..., None],
            "diffusion": grad["variance"]*(2*sigma*time)[..., None],
            "dt": grad["mean"]*b[..., None]+grad["variance"]*(sigma*sigma)[..., None]}


def interval_transition_matrix(states, edges, drift, diffusion, dt):
    """Nonnegative rows for a full real-line partition (-inf,e1],...,(en,inf).

    Rows propagate point states; a subsequent multiplication using representative
    states is a finite-volume projection, not an exact semigroup identity.
    """
    states, edges = np.asarray(states, dtype=float), np.asarray(edges, dtype=float)
    if (states.ndim != 1 or edges.ndim != 1 or len(edges) < 2
            or not np.isfinite(states).all() or edges[0] != -np.inf or edges[-1] != np.inf
            or not np.isfinite(edges[1:-1]).all() or np.any(np.diff(edges) <= 0)):
        raise ValueError("Finite one-dimensional states and a complete ordered partition required")
    m, v = gaussian_transition(states, np.zeros_like(states), drift, diffusion, dt)
    return event_probs(m[:, None], v[:, None], edges[:-1], edges[1:])[..., 1]


def quantize_simplex(probabilities, bits=24):
    """Largest-remainder nonnegative fixed-point encoding with exact row sums.

    Ties resolve by channel index. Roundoff-sized FP64 normalization error is
    removed first; this does not calibrate, truncate or infer a probability law.
    """
    p = np.asarray(probabilities, dtype=np.float64)
    if (p.ndim < 1 or p.shape[-1] < 1 or not np.isfinite(p).all() or np.any(p < 0)
            or not isinstance(bits, int) or not 1 <= bits <= 30
            or not np.allclose(p.sum(-1), 1.0, atol=1e-12, rtol=0.0)):
        raise ValueError("Normalized finite probabilities and 1..30 fractional bits required")
    scale = 1 << bits
    flat = (p/p.sum(-1, keepdims=True)).reshape(-1, p.shape[-1])
    raw = flat*scale
    quantized = np.floor(raw).astype(np.int64)
    fractions = raw-quantized
    for row in range(len(flat)):
        missing = scale-int(quantized[row].sum())
        order = np.argsort(-fractions[row], kind="stable")
        quantized[row, order[:missing]] += 1
    return quantized.reshape(p.shape)


def first_passage_upper(start, barrier, drift, diffusion, horizon):
    """Separate Brownian upper-barrier hitting fixture; no reset is modeled.

    This is intentionally a different event from event_probs. Coefficients and
    the barrier are constant until the finite horizon. Start at/above the barrier
    means a hit at time zero; below-barrier zero horizon means no hit.
    """
    x, k, b, sigma, t = np.broadcast_arrays(*[
        np.asarray(a, dtype=float) for a in (start, barrier, drift, diffusion, horizon)
    ])
    if (not all(np.isfinite(a).all() for a in (x, k, b, sigma, t))
            or np.any(sigma <= 0) or np.any(t < 0)):
        raise ValueError("Finite inputs, positive diffusion and nonnegative horizon required")
    safe_t = np.where(t > 0, t, 1.0)
    distance, scale = k-x, sigma*np.sqrt(safe_t)
    z1, z2 = (b*safe_t-distance)/scale, (-b*safe_t-distance)/scale
    log_second = 2.0*b*distance/(sigma*sigma)+log_ndtr(z2)
    with np.errstate(over="ignore"):
        answer = np.exp(log_ndtr(z1))+np.exp(log_second)
    return np.where(x >= k, 1.0, np.where(t == 0, 0.0, np.clip(answer, 0.0, 1.0)))
