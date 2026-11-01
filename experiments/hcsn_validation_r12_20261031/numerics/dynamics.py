"""Complete fixed-reset successor, retaining live density and refractory age.

The inherited renewal model is imported unchanged. These integrals add the
post-hit state law; an expected count alone is not a recurrent state transition.
All derivatives below apply to the registered moderate, constant-coefficient
domain. They are ordinary derivatives of the executed probability model.
"""

import math

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import log_ndtr, ndtr

from experiments.hcsn_regeneration_content_20261031 import renewal


def hitting_density(t, x, mu, sigma):
    """Independent scalar inverse-Gaussian density, excluding the x=0 atom."""
    if t <= 0:
        return 0.0
    return x * math.exp(-(x + mu * t) ** 2 / (2 * sigma**2 * t)) / (
        sigma * math.sqrt(2 * math.pi) * t**1.5
    )


def first_hit_jacobian(x, mu, sigma, horizon):
    """Columns x, mu, sigma, horizon; interior parameters only."""
    if x <= 0 or sigma <= 0 or horizon <= 0:
        raise ValueError("Interior first-hit derivative requires x,sigma,horizon>0")
    scale = sigma * math.sqrt(horizon)
    a, b = (-x - mu * horizon) / scale, (-x + mu * horizon) / scale
    phi = math.exp(-0.5 * a * a) / math.sqrt(2 * math.pi)
    reflected = math.exp(-2 * mu * x / sigma**2 + float(log_ndtr(b)))
    result = np.array([
        float(renewal.first_passage_cdf_dx(x, mu, sigma, horizon)),
        -2 * x * reflected / sigma**2,
        2 * x * phi / (sigma**2 * math.sqrt(horizon)) + 4 * mu * x * reflected / sigma**3,
        x * phi / (sigma * horizon**1.5),
    ])
    if not np.all(np.isfinite(result)):
        raise ArithmeticError("Unresolved first-hit derivative")
    return result


def count_jacobian(x, mu, sigma, horizon, reset, refractory):
    """All six parameter derivatives, including cycle time and reset distance."""
    if not all(math.isfinite(v) for v in (x, mu, sigma, horizon, reset, refractory)):
        raise ValueError("Finite parameters required")
    if min(x, sigma, horizon, reset, refractory) <= 0:
        raise ValueError("This derivative contract requires positive refractory and interior state")
    result = np.zeros(6)
    for n in range(int(math.ceil(horizon / refractory))):
        available = horizon - n * refractory
        if available <= 0:
            continue
        jac = first_hit_jacobian(x + n * reset, mu, sigma, available)
        result[:4] += jac
        result[4] += n * jac[0]
        result[5] -= n * jac[3]
    return result


def _normal_interval(lo, hi):
    if lo > 0:
        return ndtr(-lo) - ndtr(-hi)
    return ndtr(hi) - ndtr(lo)


def killed_functionals(x, mu, sigma, horizon, edges):
    """Unconditional active mass, moments 1/2 and interval probabilities."""
    edges = np.asarray(edges)
    if horizon <= 0:
        bins = ((edges[:-1] <= x) & (x < edges[1:])).astype(float)
        return np.r_[1.0, x, x * x, bins]
    scale = sigma * math.sqrt(horizon)
    means = (x + mu * horizon, -x + mu * horizon)
    weight = math.exp(-2 * mu * x / sigma**2)
    result = []
    for mean in means:
        a = mean / scale
        phi = math.exp(-0.5 * a * a) / math.sqrt(2 * math.pi)
        probability = float(ndtr(a))
        moments = [probability, mean * probability + scale * phi,
                   (mean * mean + scale * scale) * probability + mean * scale * phi]
        bounds = (edges - mean) / scale
        bins = [_normal_interval(lo, hi) for lo, hi in zip(bounds[:-1], bounds[1:])]
        result.append(np.r_[moments, bins])
    return result[0] - weight * result[1]


def regenerative_successor(case, edges):
    """Integrate every completed reset branch and the full recovery-age law.

    At n-th firing the sum of hitting times has density f(x+(n-1)*reset).
    After n refractory periods its live successor is the killed reset law over
    the remaining time. The recovery-age density retains the last, uncompleted
    refractory period. No average-hit-time or interval-end reset is substituted.
    """
    x, mu, sigma, horizon, reset, refractory = [case[k] for k in
        ("x", "mu", "sigma", "horizon", "reset", "refractory")]
    if min(x, sigma, horizon, reset, refractory) <= 0:
        raise ValueError("Complete successor audit uses positive interior/refractory parameters")
    active = killed_functionals(x, mu, sigma, horizon, edges)
    branch_records = []
    error_sum = 0.0
    for n in range(1, int(math.ceil(horizon / refractory)) + 1):
        distance = x + (n - 1) * reset
        available = horizon - n * refractory
        if available <= 0:
            continue
        increment, error = quad_vec(
            lambda s: hitting_density(s, distance, mu, sigma)
            * killed_functionals(reset, mu, sigma, available - s, edges),
            0.0, available, epsabs=2e-11, epsrel=2e-10,
        )
        active += increment
        error_sum += float(error)
        branch_records.append({"completed_resets": n, "active": increment.tolist(),
                               "quadrature_error_estimate": float(error)})

    def age_density(age):
        return sum(hitting_density(horizon - (n - 1) * refractory - age,
                                   x + (n - 1) * reset, mu, sigma)
                   for n in range(1, int(math.ceil(horizon / refractory)) + 1))

    recovery, recovery_error = quad_vec(
        lambda age: np.array([1.0, age, age * age]) * age_density(age),
        0.0, refractory, epsabs=2e-11, epsrel=2e-10,
    )
    return {"active": active.tolist(), "recovery": recovery.tolist(),
            "mass": float(active[0] + recovery[0]),
            "expected_count": float(renewal.expected_count(**case)),
            "active_branches": branch_records,
            "quadrature_error_estimate": error_sum + float(recovery_error)}
