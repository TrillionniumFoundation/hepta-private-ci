"""Repeated Brownian events with independent Erlang recovery in physical seconds.

Every hit resets to a fixed positive boundary distance after recovery. Holding
mu/sigma/boundary fixed makes successive hitting times independent. Their sum
is a first-hit time at the sum of the distances; recovery sums are Erlang.
This identity gives positive quadrature, with no voltage or time mesh.
"""

import math

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import gammaln

from .event_kernel import DomainError, first_hit, first_hit_gradient
from .generator import recovery_discount


def count_tail_bound(initial_gap, reset_gap, drift, sigma, time, recovery_mean, phases, included):
    """Chernoff/geometric upper bound on sum_{n>included} Pr(N(time)>=n)."""
    first_hit(initial_gap, drift, sigma, time)
    recovery_discount(recovery_mean, phases, 1.0)
    if not math.isfinite(reset_gap) or reset_gap <= 0 or type(included) is not int or included < 1:
        raise DomainError("Positive reset gap and at least one included event required")
    kappa = max(0.0, -2 * drift / sigma**2) + 1 / reset_gap
    tilt = (kappa * sigma**2 / (2 * reset_gap) if drift < 0
            else drift / reset_gap + sigma**2 / (2 * reset_gap**2))
    beta = math.hypot(drift, math.sqrt(2 * tilt) * sigma)
    kappa = 2 * tilt / (beta + drift) if drift >= 0 else (beta - drift) / sigma**2
    log_ratio = -kappa * reset_gap - phases * math.log1p(tilt * recovery_mean / phases)
    log_bound = tilt * time - kappa * initial_gap + included * log_ratio - math.log(-math.expm1(log_ratio))
    return dict(bound=math.exp(log_bound) if log_bound < 709 else math.inf,
                log_bound=log_bound, tilt=tilt)


def expected_count(initial_gap, reset_gap, drift, sigma, time, recovery_mean, phases=2,
                   *, tail_tolerance=1e-10, max_events=256, included_events=None):
    """Expected repeated count and analytic-integrand parameter derivatives.

    Count truncation has a proved bound. Quadrature has a numerical estimate.
    Derivative-tail truncation is NOT covered by the count-tail bound; compare
    included_events values and independent finite differences before training.
    """
    first_hit(initial_gap, drift, sigma, time)
    recovery_discount(recovery_mean, phases, 1.0)
    if (not math.isfinite(reset_gap) or reset_gap <= 0 or not 1e-14 <= tail_tolerance <= 1e-4
            or type(max_events) is not int or not 1 <= max_events <= 512):
        raise DomainError("Positive reset gap, tail tolerance [1e-14,1e-4], and 1..512 terms required")
    count = 1
    if included_events is None:
        while count_tail_bound(initial_gap, reset_gap, drift, sigma, time, recovery_mean, phases, count)["bound"] > tail_tolerance:
            count += 1
            if count > max_events:
                raise DomainError("Renewal tail cannot be certified within the explicit event budget")
    elif type(included_events) is int and 1 <= included_events <= max_events:
        count = included_events
    else:
        raise DomainError("included_events must lie inside the event budget")
    tail = count_tail_bound(initial_gap, reset_gap, drift, sigma, time, recovery_mean, phases, count)
    if tail["bound"] > tail_tolerance:
        raise DomainError("Requested finite renewal sum does not meet the declared count-tail budget")
    names = ("initial_gap", "reset_gap", "drift", "sigma", "recovery_mean")
    total = np.zeros(6)
    rows, estimated_error = [], 0.0
    rate = phases / recovery_mean
    for event in range(1, count + 1):
        gap = initial_gap + (event - 1) * reset_gap
        def event_vector(remaining):
            probability = first_hit(gap, drift, sigma, remaining)["probability"]
            gradient = first_hit_gradient(gap, drift, sigma, remaining)
            return np.array([probability, gradient["distance"], (event-1)*gradient["distance"],
                             gradient["drift"], gradient["sigma"], 0.0])
        if event == 1:
            value, error = event_vector(time), 0.0
        else:
            shape = phases * (event - 1)
            def integrand(recovery):
                if recovery <= 0 or recovery >= time:
                    return np.zeros(6)
                density = math.exp(shape * math.log(rate) + (shape-1)*math.log(recovery)
                                   -rate*recovery - float(gammaln(shape)))
                result = event_vector(time - recovery)
                result[-1] = result[0] * (rate * recovery - shape) / recovery_mean
                return density * result
            value, error = quad_vec(integrand, 0.0, time, epsabs=tail_tolerance/(20*count),
                                    epsrel=2e-11, limit=500)
        total += value
        estimated_error += float(error)
        rows.append(float(value[0]))
    return dict(expected_count=float(total[0]), gradient=dict(zip(names, total[1:].tolist())),
                event_survival=rows, included_events=count, count_tail_bound=tail["bound"],
                count_log_tail_bound=tail["log_bound"], quadrature_error_estimate=estimated_error,
                gradient_tail_certified=False, roundoff_included=False)


def sample_counts(initial_gap, reset_gap, drift, sigma, time, recovery_mean, phases=2,
                  *, paths=100000, seed=20261031, max_events=512):
    """Independent exact event-time Monte Carlo; no Euler path discretization."""
    first_hit(initial_gap, drift, sigma, time)
    recovery_discount(recovery_mean, phases, 1.0)
    if (not math.isfinite(reset_gap) or reset_gap <= 0 or type(paths) is not int or not 1 <= paths <= 2000000
            or type(max_events) is not int or not 1 <= max_events <= 4096):
        raise DomainError("Positive reset gap and bounded positive path count required")
    rng = np.random.default_rng(seed)
    def hit_times(gap, size):
        if drift == 0:
            return (gap / (sigma * rng.normal(size=size)))**2
        duration = rng.wald(gap / abs(drift), gap**2 / sigma**2, size=size)
        if drift < 0:
            duration[rng.random(size) > math.exp(2 * drift * gap / sigma**2)] = math.inf
        return duration
    clock = hit_times(initial_gap, paths)
    counts = np.zeros(paths, dtype=int)
    for _ in range(max_events):
        live = np.flatnonzero(clock <= time)
        if not len(live):
            return counts
        counts[live] += 1
        clock[live] += rng.gamma(phases, recovery_mean / phases, size=len(live))
        clock[live] += hit_times(reset_gap, len(live))
    if not np.any(clock <= time):
        return counts
    raise DomainError("Sample path exceeded the explicit event budget")
