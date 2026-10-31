"""Analytic first-passage and fixed-reset renewal operators (NumPy/SciPy).

X(t) = x + mu*t + sigma*W(t), x >= 0, absorbs at zero.  Each hit is
counted immediately, followed by deterministic refractory time and reset > 0.
All parameters stay fixed throughout the requested horizon.  See MATHEMATICS.md.
"""

import numpy as np
from scipy.special import erfcx, log_ndtr, ndtr


TAIL_ATOL = 1e-13
TAIL_RTOL = 2e-13
MAX_TERMS = 10000
_LOG_2PI = np.log(2.0 * np.pi)


def _broadcast(x, mu, sigma, horizon):
    arrays = np.broadcast_arrays(*[np.asarray(v, dtype=np.float64)
                                  for v in (x, mu, sigma, horizon)])
    if any(np.any(~np.isfinite(v)) for v in arrays):
        raise ValueError("x, mu, sigma and horizon must be finite")
    if np.any(arrays[0] < 0) or np.any(arrays[2] <= 0) or np.any(arrays[3] < 0):
        raise ValueError("Require x >= 0, sigma > 0 and horizon >= 0")
    return arrays


def _renewal_args(x, mu, sigma, horizon, reset, refractory):
    values = np.broadcast_arrays(*_broadcast(x, mu, sigma, horizon),
                                 np.asarray(reset, dtype=np.float64),
                                 np.asarray(refractory, dtype=np.float64))
    if np.any(~np.isfinite(values[4])) or np.any(values[4] <= 0):
        raise ValueError("reset must be finite and strictly positive")
    if np.any(~np.isfinite(values[5])) or np.any(values[5] < 0):
        raise ValueError("refractory must be finite and nonnegative")
    return values


def _mills_and_deficit(a):
    """R(a)=Phi(-a)/phi(a), and 1-a*R(a), for a >= 0.

    The second expression needs its asymptotic expansion to avoid cancellation.
    """
    a = np.asarray(a, dtype=np.float64)
    mills = np.sqrt(np.pi / 2.0) * erfcx(a / np.sqrt(2.0))
    deficit = 1.0 - a * mills
    large = a >= 20.0
    if np.any(large):
        inv2 = 1.0 / (a[large] * a[large])
        term = inv2.copy()
        series = term.copy()
        for k in range(1, 11):
            term *= -(2 * k + 1) * inv2
            series += term
        deficit = np.array(deficit, copy=True)
        deficit[large] = series
    return mills, deficit


def _cdf_and_dx(x, mu, sigma, time, gradient):
    """Internal validated array operation; time may be negative for count tails."""
    x, mu, sigma, time = np.broadcast_arrays(x, mu, sigma, time)
    cdf = np.zeros(x.shape, dtype=np.float64)
    dx = np.zeros(x.shape, dtype=np.float64) if gradient else None
    live = time > 0
    if np.any(live):
        xx, mm, ss, tt = (v[live] for v in (x, mu, sigma, time))
        scale = ss * np.sqrt(tt)
        z1 = (-xx - mm * tt) / scale
        z2 = (-xx + mm * tt) / scale
        log_b = np.empty_like(z2)
        negative_z = z2 <= 0
        log_b[negative_z] = (-0.5 * z1[negative_z] ** 2
                            + np.log(0.5 * erfcx(-z2[negative_z] / np.sqrt(2.0))))
        log_b[~negative_z] = (-2.0 * mm[~negative_z] * xx[~negative_z]
                             / ss[~negative_z] ** 2 + log_ndtr(z2[~negative_z]))
        cdf[live] = np.minimum(1.0, np.exp(np.logaddexp(log_ndtr(z1), log_b)))
        if gradient:
            base = np.exp(np.log(2.0) - 0.5 * z1 ** 2
                          - 0.5 * _LOG_2PI - np.log(scale))
            deriv = -base
            negative_mu = mm < 0
            if np.any(negative_mu):
                mills, deficit = _mills_and_deficit(-z2[negative_mu])
                bracket = deficit + xx[negative_mu] / scale[negative_mu] * mills
                deriv[negative_mu] = -base[negative_mu] * bracket
            positive_mu = mm > 0
            if np.any(positive_mu):
                deriv[positive_mu] -= np.exp(
                    np.log(2.0 * mm[positive_mu]) - 2.0 * np.log(ss[positive_mu])
                    + log_b[positive_mu])
            dx[live] = deriv
    # x=0 is an atom at time zero, including a zero-length observation interval.
    immediate = (x == 0) & (time >= 0)
    cdf[immediate] = 1.0
    if gradient:
        dx[(x == 0) & (time == 0)] = np.nan  # No finite spatial derivative here.
    return cdf, dx


def first_passage_cdf(x, mu, sigma, horizon):
    """Probability of hitting zero by horizon; x=0 counts immediately."""
    return _cdf_and_dx(*_broadcast(x, mu, sigma, horizon), False)[0]


def first_passage_cdf_dx(x, mu, sigma, horizon):
    """Spatial derivative; at x=0 use the right derivative (NaN at horizon=0)."""
    return _cdf_and_dx(*_broadcast(x, mu, sigma, horizon), True)[1]


def first_passage_density(x, mu, sigma, time):
    """Continuous hitting-time density. The x=0 atom is not a density value."""
    x, mu, sigma, time = _broadcast(x, mu, sigma, time)
    result = np.zeros(x.shape, dtype=np.float64)
    valid = (x > 0) & (time > 0)
    if np.any(valid):
        xx, mm, ss, tt = (v[valid] for v in (x, mu, sigma, time))
        z = (xx + mm * tt) / (ss * np.sqrt(tt))
        result[valid] = np.exp(np.log(xx) - np.log(ss) - 0.5 * _LOG_2PI
                               - 1.5 * np.log(tt) - 0.5 * z ** 2)
    return result


def killed_density(y, x, mu, sigma, horizon):
    """Density on y>=0 before the first hit. Requires positive horizon."""
    x, mu, sigma, horizon, y = np.broadcast_arrays(
        *_broadcast(x, mu, sigma, horizon), np.asarray(y, dtype=np.float64))
    if np.any(horizon <= 0) or np.any(y < 0) or np.any(~np.isfinite(y)):
        raise ValueError("killed_density requires horizon>0 and finite y>=0")
    variance = sigma ** 2 * horizon
    log_normal = -0.5 * (y - x - mu * horizon) ** 2 / variance
    log_normal -= 0.5 * np.log(2.0 * np.pi * variance)
    return np.exp(log_normal) * (-np.expm1(-2.0 * x * y / variance))


def _indices(n):
    n = np.asarray(n, dtype=np.float64)
    if np.any(~np.isfinite(n)) or np.any(n < 0) or np.any(n != np.floor(n)):
        raise ValueError("count index must be a finite nonnegative integer")
    return n


def count_tail(n, x, mu, sigma, horizon, reset, refractory):
    """P(N_horizon >= n), with tail(0)=1; all arguments broadcast."""
    n, x, mu, sigma, horizon, reset, refractory = np.broadcast_arrays(
        _indices(n), *_renewal_args(x, mu, sigma, horizon, reset, refractory))
    offset = np.maximum(n - 1.0, 0.0)
    result = _cdf_and_dx(x + offset * reset, mu, sigma,
                         horizon - offset * refractory, False)[0]
    return np.where(n == 0, 1.0, result)


def count_pmf(n, x, mu, sigma, horizon, reset, refractory):
    """P(N_horizon == n); individual probabilities, not a renormalized table."""
    n = _indices(n)
    return (count_tail(n, x, mu, sigma, horizon, reset, refractory)
            - count_tail(n + 1, x, mu, sigma, horizon, reset, refractory))


def _zero_refractory_bounds(terms, x, mu, sigma, horizon, reset):
    """Conservative omitted mean/absolute-gradient bounds after `terms` tails."""
    mean_bound = np.zeros(x.shape, dtype=np.float64)
    dx_bound = np.zeros(x.shape, dtype=np.float64)
    live = horizon > 0
    if not np.any(live):
        return mean_bound, dx_bound
    xx, mm, ss, hh, rr = (v[live] for v in (x, mu, sigma, horizon, reset))
    a = xx + terms * rr
    scale = ss * np.sqrt(hh)
    q = (a - np.maximum(-mm, 0.0) * hh) / scale
    good = q > 0
    mb = np.full_like(q, np.inf)
    db = np.full_like(q, np.inf)
    if np.any(good):
        qq = q[good]
        _, deficit = _mills_and_deficit(qq)
        phi = np.exp(-0.5 * qq ** 2 - 0.5 * _LOG_2PI)
        mb[good] = 2.0 * ndtr(-qq) + 2.0 * scale[good] / rr[good] * phi * deficit
        z = (a[good] + mm[good] * hh[good]) / scale[good]
        ratio_log = -(2.0 * (a[good] + mm[good] * hh[good]) * rr[good]
                      + rr[good] ** 2) / (2.0 * scale[good] ** 2)
        gaussian_sum = (2.0 * np.exp(-0.5 * z ** 2 - 0.5 * _LOG_2PI)
                        / scale[good] / (-np.expm1(ratio_log)))
        db[good] = gaussian_sum + 2.0 * np.maximum(mm[good], 0.0) / ss[good] ** 2 * mb[good]
    mean_bound[live], dx_bound[live] = mb, db
    return mean_bound, dx_bound


def _sum_counts(x, mu, sigma, horizon, reset, refractory, gradient):
    x, mu, sigma, horizon, reset, refractory = _renewal_args(
        x, mu, sigma, horizon, reset, refractory)
    mean = np.zeros(x.shape, dtype=np.float64)
    dx = np.zeros(x.shape, dtype=np.float64) if gradient else None
    zero_refractory = refractory == 0
    mean_bound = np.zeros(x.shape, dtype=np.float64)
    dx_bound = np.zeros(x.shape, dtype=np.float64)
    for index in range(MAX_TERMS):
        tail, derivative = _cdf_and_dx(x + index * reset, mu, sigma,
                                      horizon - index * refractory, gradient)
        mean += tail
        if gradient:
            dx += derivative
        terms = index + 1
        finite_finished = np.all(zero_refractory | (horizon - terms * refractory <= 0))
        infinite_finished = True
        if np.any(zero_refractory):
            mb, db = _zero_refractory_bounds(terms, x, mu, sigma, horizon, reset)
            mean_bound = np.where(zero_refractory, mb, 0.0)
            dx_bound = np.where(zero_refractory, db, 0.0)
            infinite_finished = np.all(mean_bound <= TAIL_ATOL + TAIL_RTOL * np.abs(mean))
            if gradient:
                threshold = TAIL_ATOL + TAIL_RTOL * np.nan_to_num(np.abs(dx))
                infinite_finished &= np.all(dx_bound <= threshold)
        if finite_finished and infinite_finished:
            return {"mean": mean, "dx": dx, "summed_terms": terms,
                    "mean_remainder_bound": mean_bound,
                    "dx_remainder_bound": dx_bound if gradient else None}
    raise RuntimeError(f"Renewal sum exceeded {MAX_TERMS} terms; increase time scale/reset")


def expected_count(x, mu, sigma, horizon, reset, refractory):
    """Expected number of hits, including all possible repeats in the interval."""
    return _sum_counts(x, mu, sigma, horizon, reset, refractory, False)["mean"]


def expected_count_dx(x, mu, sigma, horizon, reset, refractory):
    """Derivative of expected_count with respect to initial distance x only."""
    return _sum_counts(x, mu, sigma, horizon, reset, refractory, True)["dx"]


def expected_count_details(x, mu, sigma, horizon, reset, refractory):
    """Mean, dx, number of summed terms and certified mathematical tail bounds."""
    return _sum_counts(x, mu, sigma, horizon, reset, refractory, True)
