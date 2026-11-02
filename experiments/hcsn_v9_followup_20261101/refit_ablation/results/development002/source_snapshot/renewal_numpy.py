"""Exact selected NumPy/SciPy definitions from frozen v2; no torch substitute."""
from dataclasses import dataclass
import math
import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr, log_ndtr

@dataclass(frozen=True)
class Physics:
    nu: float
    sigma: float
    reset: float
    refractory: float

    def validate(self):
        if self.sigma <= 0 or self.reset <= 0 or self.refractory <= 0:
            raise ValueError("sigma, reset, and refractory must be positive")


def first_passage_cdf(t, x, nu, sigma):
    """Stable lower first-passage CDF; t<=0 gives zero, x>0 required."""
    t, x = np.broadcast_arrays(np.asarray(t, float), np.asarray(x, float))
    if np.any(x <= 0) or sigma <= 0:
        raise ValueError("positive initial gap and volatility required")
    active = t > 0
    safe_t = np.where(active, t, 1.0)
    scale = sigma * np.sqrt(safe_t)
    a = (-x - nu * safe_t) / scale
    b = (-x + nu * safe_t) / scale
    reflected = np.exp(np.minimum(-2 * nu * x / sigma**2 + log_ndtr(b), 0))
    result = np.where(active, ndtr(a) + reflected, 0)
    if np.any(result > 1 + 1e-10):
        raise ArithmeticError("first-passage probability exceeds one")
    return np.clip(result, 0, 1)


def integrated_cdf(t, x, nu, sigma, tolerance=1e-9):
    """Independent adaptive integral of the first-passage density, with work."""
    if t <= 0:
        return 0.0, 0
    def density(s):
        if s <= 0:
            return 0.0
        log_f = (math.log(x / sigma) - 0.5 * math.log(2 * math.pi)
                 - 1.5 * math.log(s) - (x + nu * s)**2 / (2 * sigma**2 * s))
        return math.exp(log_f) if log_f > -745 else 0.0
    mode = 2 * x*x / (3 * sigma*sigma + math.sqrt(9 * sigma**4 + 4 * nu*nu*x*x))
    points = sorted({v for v in (mode / 10, mode, mode * 10) if 0 < v < t})
    answer = quad(density, 0, t, epsabs=tolerance, epsrel=tolerance,
                  points=points, limit=200, full_output=1)
    value, error, info = answer[:3]
    if len(answer) > 3 or error > max(10 * tolerance, abs(value) * 10 * tolerance):
        raise ArithmeticError(f"first-passage integration failed: {error}")
    return float(value), int(info["neval"])


def renewal_counts(x, horizon, physics, remaining=0.0, cap=32, numerical=False,
                   tolerance=1e-9, reset_enabled=True, refractory_enabled=True):
    """Return P(N=n), n=0..cap-1, and explicit evaluation work.

    cap is a checked support bound, never a last-bin overflow bucket.
    reset_enabled=False is an absorbing, at-most-one-event MODEL ablation.
    refractory_enabled=False is a zero-refractory MODEL ablation; tail checked.
    """
    physics.validate()
    if remaining > 0 and not np.isclose(x, physics.reset):
        raise ValueError("refractory observations must carry the reset gap")
    t = float(horizon) - max(float(remaining), 0.0)
    if t <= 0:
        answer = np.zeros(cap); answer[0] = 1.0
        return answer, {"cdf_terms": 0, "integration_evaluations": 0}
    delay = physics.refractory if refractory_enabled else 0.0
    n = np.arange(1, cap + 1, dtype=float)
    elapsed = t - (n - 1) * delay
    distance = x + (n - 1) * physics.reset
    if numerical:
        values = [integrated_cdf(a, b, physics.nu, physics.sigma, tolerance)
                  for a, b in zip(elapsed, distance)]
        tails = np.array([v[0] for v in values]); work = sum(v[1] for v in values)
    else:
        tails = first_passage_cdf(elapsed, distance, physics.nu, physics.sigma)
        work = 0
    if not reset_enabled:
        tails[1:] = 0
    if tails[-1] > max(1e-10, tolerance * 10):
        raise ValueError(f"event support exceeds cap={cap}; missing mass={tails[-1]}")
    probs = np.r_[1.0, tails[:-1]] - tails
    if probs.min() < -max(1e-10, tolerance * 10):
        raise ArithmeticError("nonmonotone event-count tails")
    probs = np.maximum(probs, 0)
    if abs(probs.sum() - 1) > max(1e-9, tolerance * 20):
        raise ArithmeticError("event-count mass not conserved")
    correction = float(1 - probs.sum())
    probs /= probs.sum()
    return probs, {"cdf_terms": int(np.count_nonzero(elapsed > 0)),
                   "integration_evaluations": int(work), "omitted_tail_mass": float(tails[-1]),
                   "normalization_correction": correction}


def content_from_counts(probabilities, initial, transition):
    z = np.asarray(initial, float)
    transition = np.asarray(transition, float)
    if np.any(transition < 0) or not np.allclose(transition.sum(axis=0), 1):
        raise ValueError("transition must be column-stochastic")
    result = np.zeros_like(z)
    for weight in probabilities:
        result += weight * z
        z = transition @ z
    return result


def sample_counts(rng, physics, x, horizon, size, remaining=0.0):
    """Independent exact IG event sampling; no CDF or time-step detection."""
    if physics.nu >= 0:
        raise ValueError("IG simulator contract requires negative drift")
    hitting = rng.wald(x / -physics.nu, x*x / physics.sigma**2, size=size)
    hitting += remaining
    counts = np.zeros(size, dtype=int)
    while np.any(hitting <= horizon):
        active = hitting <= horizon
        counts[active] += 1
        hitting[active] += physics.refractory + rng.wald(
            physics.reset / -physics.nu, physics.reset**2 / physics.sigma**2,
            size=int(active.sum()))
    return counts
