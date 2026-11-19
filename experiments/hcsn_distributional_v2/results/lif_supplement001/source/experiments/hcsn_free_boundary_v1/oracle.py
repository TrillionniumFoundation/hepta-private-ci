"""Exact stationary regenerative impulse-control oracle and scalar references.

The model is arithmetic Brownian motion, linear firing reward, a fixed reset,
frozen refractory state, and infinite-horizon exponential discount.  This is
not the He--Xiong financing model and not a finite-horizon network solution.
See CONTRACT.md and MATH.md for the precise event contract and verification.
"""

from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import log_ndtr, ndtr


PARAMETER_NAMES = ("mu", "sigma", "rho", "K", "r", "tau")


@dataclass(frozen=True)
class OracleParams:
    mu: float = 0.25
    sigma: float = 0.7
    rho: float = 0.4
    K: float = 0.8
    r: float = -0.2
    tau: float = 0.3

    def validate(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("All oracle parameters must be finite.")
        if self.sigma < 0 or self.rho <= 0 or self.tau < 0:
            raise ValueError("Require sigma >= 0, rho > 0, and tau >= 0.")
        if self.r >= self.K:
            raise ValueError("Require reset r < execution cost K.")


@dataclass(frozen=True)
class BoundarySolution:
    boundary: float
    kappa: float
    q: float
    value_at_boundary: float
    gradients: dict
    residual: float
    root_jacobian: float
    regime: str


def kappa(mu, sigma, rho):
    """Positive root of sigma^2*k^2/2 + mu*k - rho = 0.

    A deterministic nonincreasing state has no finite positive root.
    """
    if sigma < 0 or rho <= 0:
        raise ValueError("Require sigma >= 0 and rho > 0.")
    if sigma == 0:
        return rho / mu if mu > 0 else math.inf
    discriminant = math.hypot(mu, math.sqrt(2 * rho) * sigma)
    if mu >= 0:
        return 2 * rho / (discriminant + mu)
    return (discriminant - mu) / (sigma * sigma)


def solve_boundary(params):
    """Solve the unique global optimum and its six implicit derivatives."""
    params.validate()
    mu, sigma, rho, K, r, tau = (getattr(params, n) for n in PARAMETER_NAMES)
    kap = kappa(mu, sigma, rho)
    if math.isinf(kap):
        return BoundarySolution(K, kap, 0.0, 0.0, {}, 0.0, math.inf,
                                "deterministic_nonincreasing")
    dimensionless_gap = rho * tau + kap * (K - r)
    # expm1 avoids cancelling 1 against exp(-small) at nearly degenerate roots.
    def residual(y):
        return y + math.expm1(-dimensionless_gap - y)
    y = brentq(residual, 0.0, 1.0, xtol=5e-15,
               rtol=4 * np.finfo(float).eps)
    b = K + y / kap
    q = math.exp(-dimensionless_gap - y)
    one_minus_q = -math.expm1(-dimensionless_gap - y)
    jacobian = kap * one_minus_q
    omega = math.hypot(mu, math.sqrt(2 * rho) * sigma)
    kap_grad = {"mu": -kap / omega,
                "sigma": -sigma * kap * kap / omega,
                "rho": 1 / omega}
    a = y / kap
    distance = a + K - r
    sensitivity_to_kappa = a - q * distance
    derivatives = {n: -sensitivity_to_kappa * kap_grad[n] / jacobian
                   for n in ("mu", "sigma", "rho")}
    derivatives["rho"] += tau * q / jacobian
    derivatives.update(K=kap / jacobian, r=-kap * q / jacobian,
                       tau=rho * q / jacobian)
    return BoundarySolution(b, kap, q, 1 / kap, derivatives,
                            residual(y), jacobian,
                            "diffusion" if sigma > 0 else "deterministic_increasing")


def value(x, params, solution=None):
    """Optimal infinite-horizon value, including immediate intervention."""
    sol = solve_boundary(params) if solution is None else solution
    x = np.asarray(x, dtype=float)
    if math.isinf(sol.kappa):
        return np.maximum(x - params.K, 0.0)
    displacement = x - sol.boundary
    continuation = np.exp(sol.kappa * np.minimum(displacement, 0)) / sol.kappa
    return np.where(displacement < 0, continuation, displacement + 1 / sol.kappa)


def intervention_value(x, params, solution=None):
    sol = solve_boundary(params) if solution is None else solution
    return np.asarray(x) - params.K + math.exp(-params.rho * params.tau) * value(params.r, params, sol)


def continuation_gap(x, params, solution=None):
    """Value minus immediate-fire value; this is not an event probability."""
    sol = solve_boundary(params) if solution is None else solution
    return value(x, params, sol) - intervention_value(x, params, sol)


def threshold_policy_value(x, boundary, params):
    """Exact value of any fixed upper threshold above both K and reset r."""
    params.validate()
    if boundary <= max(params.K, params.r):
        raise ValueError("A fixed reward-positive threshold must exceed K and r.")
    kap = kappa(params.mu, params.sigma, params.rho)
    if math.isinf(kap):
        return np.where(np.asarray(x) >= boundary, np.asarray(x) - params.K, 0.0)
    log_q = -params.rho * params.tau - kap * (boundary - params.r)
    at_boundary = (boundary - params.K) / (-math.expm1(log_q))
    x = np.asarray(x, dtype=float)
    below = np.exp(kap * np.minimum(x - boundary, 0)) * at_boundary
    above = x - params.K + math.exp(log_q) * at_boundary
    return np.where(x < boundary, below, above)


def _event_inputs(x, boundary, time, mu, sigma):
    if sigma < 0 or not all(np.isfinite([x, boundary, mu, sigma])):
        raise ValueError("Finite event parameters and sigma >= 0 required.")
    time = np.asarray(time, dtype=float)
    if np.any(time < 0) or np.any(~np.isfinite(time)):
        raise ValueError("Finite nonnegative observation times required.")
    return boundary - x, time


def first_passage_cdf(x, boundary, time, mu, sigma):
    """P(first upper hit <= time); an already-hit start has an atom at zero."""
    distance, time = _event_inputs(x, boundary, time, mu, sigma)
    if distance <= 0:
        return np.ones_like(time)
    if sigma == 0:
        return (time >= distance / mu).astype(float) if mu > 0 else np.zeros_like(time)
    safe_time = np.maximum(time, np.finfo(float).tiny)
    scale = sigma * np.sqrt(safe_time)
    z1 = (mu * safe_time - distance) / scale
    z2 = (-mu * safe_time - distance) / scale
    log_second = 2 * mu * distance / (sigma * sigma) + log_ndtr(z2)
    result = ndtr(z1) + np.exp(np.minimum(log_second, 0))
    return np.where(time > 0, np.clip(result, 0, 1), 0.0)


def first_passage_survival(x, boundary, time, mu, sigma):
    """Stable survival probability, retaining small upper-tail differences."""
    distance, time = _event_inputs(x, boundary, time, mu, sigma)
    if distance <= 0:
        return np.zeros_like(time)
    if sigma == 0:
        return 1 - first_passage_cdf(x, boundary, time, mu, sigma)
    safe_time = np.maximum(time, np.finfo(float).tiny)
    scale = sigma * np.sqrt(safe_time)
    log_left = log_ndtr((distance - mu * safe_time) / scale)
    log_right = 2 * mu * distance / sigma**2 + log_ndtr((-distance - mu * safe_time) / scale)
    result = np.exp(log_left) * (-np.expm1(np.minimum(log_right - log_left, 0)))
    return np.where(time > 0, np.clip(result, 0, 1), 1.0)


def first_passage_density(x, boundary, time, mu, sigma):
    """Continuous first-hit density; deterministic/initial-hit atoms excluded."""
    distance, time = _event_inputs(x, boundary, time, mu, sigma)
    if distance <= 0 or sigma == 0:
        return np.zeros_like(time)
    safe_time = np.maximum(time, np.finfo(float).tiny)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        log_f = (math.log(distance / (sigma * math.sqrt(2 * math.pi)))
                 - 1.5 * np.log(safe_time)
                 - (distance - mu * safe_time)**2 / (2 * sigma**2 * safe_time))
    return np.where(time > 0, np.exp(log_f), 0.0)


def discounted_hitting(x, boundary, time, mu, sigma, rho):
    """E[exp(-rho*T_hit) 1(T_hit <= time)] from an exponential density tilt."""
    distance, time = _event_inputs(x, boundary, time, mu, sigma)
    if rho <= 0:
        raise ValueError("rho must be positive.")
    if distance <= 0:
        return np.ones_like(time)
    if sigma == 0:
        if mu <= 0:
            return np.zeros_like(time)
        return math.exp(-rho * distance / mu) * (time >= distance / mu)
    omega = math.hypot(mu, math.sqrt(2 * rho) * sigma)
    return math.exp(-kappa(mu, sigma, rho) * distance) * first_passage_cdf(0.0, distance, time, omega, sigma)


def finite_time_threshold_value(x, boundary, params, horizon, atol=1e-12, max_terms=100000):
    """Repeated-firing value by a finite or convergent exact hitting-time series.

    The nth firing time has law T_hit(d0+(n-1)*d_reset)+(n-1)*tau.
    `series_tail_upper_bound` bounds only mathematical series truncation; it
    is not an interval-arithmetic certificate for floating-point evaluation.
    The threshold is fixed, not optimized for the supplied terminal horizon.
    """
    params.validate()
    if x >= boundary or boundary <= max(params.K, params.r):
        raise ValueError("Require subthreshold start and boundary above K and reset.")
    if not math.isfinite(horizon) or horizon < 0 or atol <= 0 or max_terms < 1:
        raise ValueError("Finite nonnegative horizon and positive accuracy/term limits required.")
    kap = kappa(params.mu, params.sigma, params.rho)
    if horizon == 0 or math.isinf(kap):
        return {"value": 0.0, "series_tail_upper_bound": 0.0, "terms": 0,
                "kind": "finite_time_fixed_threshold_exact_series"}
    initial_distance, reset_distance = boundary - x, boundary - params.r
    log_q = -params.rho * params.tau - kap * reset_distance
    reward = boundary - params.K
    infinite_value = reward * math.exp(-kap * initial_distance) / (-math.expm1(log_q))
    terms = []
    for n in range(1, max_terms + 1):
        refractory_elapsed = (n - 1) * params.tau
        remaining = horizon - refractory_elapsed
        if remaining <= 0:
            return {"value": math.fsum(terms), "series_tail_upper_bound": 0.0,
                    "terms": n - 1, "kind": "finite_time_fixed_threshold_exact_series"}
        distance = initial_distance + (n - 1) * reset_distance
        h = float(discounted_hitting(0.0, distance, remaining, params.mu, params.sigma, params.rho))
        terms.append(reward * math.exp(-params.rho * refractory_elapsed) * h)
        tail = infinite_value * math.exp(n * log_q)
        if tail <= atol:
            return {"value": math.fsum(terms), "series_tail_upper_bound": tail,
                    "terms": n, "kind": "finite_time_fixed_threshold_exact_series"}
    raise RuntimeError("Finite-time renewal series exceeded max_terms before its tail tolerance.")


def renewal_reference(x, boundary, params, horizon, dt):
    """Finite-time fixed-threshold renewal quadrature with repeated firings.

    Discounted first-hit bin masses are exact; continuation time is rounded
    to the next grid point.  Therefore this is a convergent numerical reference,
    not an exact finite-horizon optimum.  Refractory duration must align to dt.
    """
    params.validate()
    if params.sigma <= 0 or x >= boundary or boundary <= max(params.K, params.r):
        raise ValueError("Renewal reference requires diffusion and subthreshold start/reset.")
    if horizon <= 0 or dt <= 0:
        raise ValueError("Positive horizon and dt required.")
    refractory_steps = round(params.tau / dt)
    nsteps = round(horizon / dt)
    if not math.isclose(refractory_steps * dt, params.tau, abs_tol=1e-10):
        raise ValueError("Refractory duration must be an integer multiple of dt.")
    if not math.isclose(nsteps * dt, horizon, abs_tol=1e-10):
        raise ValueError("Horizon must be an integer multiple of dt.")
    times = np.arange(nsteps + 1) * dt
    hr = discounted_hitting(params.r, boundary, times, params.mu, params.sigma, params.rho)
    hx = discounted_hitting(x, boundary, times, params.mu, params.sigma, params.rho)
    mr, mx = np.diff(hr), np.diff(hx)
    reward = boundary - params.K
    discount_refractory = math.exp(-params.rho * params.tau)
    after_reset = np.zeros(nsteps + 1)
    from_start = np.zeros(nsteps + 1)
    for n in range(1, nsteps + 1):
        available = n - refractory_steps
        reset_tail = after_reset[available - 1::-1] if available > 0 else np.empty(0)
        after_reset[n] = reward * hr[n] + discount_refractory * np.dot(mr[:max(available, 0)], reset_tail)
        from_start[n] = reward * hx[n] + discount_refractory * np.dot(mx[:max(available, 0)], reset_tail)
    return {"times": times, "value": from_start, "reset_value": after_reset,
            "single_fire_value": reward * hx, "dt": dt,
            "kind": "fixed_threshold_finite_time_renewal_quadrature"}
