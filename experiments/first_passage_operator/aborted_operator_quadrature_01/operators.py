"""Finite regenerative propagation on active and remaining-refractory states.

Only the renewal time convolution is quadrature. Spatial exponential payoffs
have a closed killed-kernel transform; event counts and discounted occupation
use analytic first-passage weights. No mass is silently renormalized.
"""

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np
from scipy.integrate import quad

from experiments.first_passage_cell.kernels import first_passage


@dataclass(frozen=True)
class RegenerativeSpec:
    mu: float
    sigma: float
    reset: float
    refractory: float
    discount: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(x) for x in vars(self).values()):
            raise ValueError("finite dynamics required")
        if self.sigma <= 0 or self.reset <= 0 or self.refractory <= 0 or self.discount < 0:
            raise ValueError("positive diffusion/reset/refractory and nonnegative discount required")


def killed_laplace(distance, mu, sigma, horizon, decay):
    """Integral exp(-decay*y) K_t(distance,dy), without a spatial grid."""
    x, t, z = np.broadcast_arrays(np.asarray(distance, float), np.asarray(horizon, float),
                                   np.asarray(decay, float))
    if np.any(x <= 0) or np.any(t < 0) or np.any(z < 0) or not np.isfinite(z).all():
        raise ValueError("positive starting distance, time>=0 and finite decay>=0 required")
    tilted = first_passage(x, mu - sigma * sigma * z, sigma, t)
    log_value = tilted["log_S"] - z * x + (0.5 * sigma * sigma * z * z - mu * z) * t
    if np.any(log_value > 1e-10):
        raise ArithmeticError("killed transform exceeds unit mass")
    return np.exp(np.minimum(log_value, 0.0))


def _log_interval(log_upper, log_lower):
    difference = np.minimum(np.asarray(log_lower) - np.asarray(log_upper), 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = log_upper + np.log(-np.expm1(difference))
    return np.where(np.isneginf(log_upper), -np.inf, result)


@lru_cache(maxsize=12)
def _quadrature_rule(order):
    return np.polynomial.legendre.leggauss(order)


def _renewal_terms(spec, distance, horizon):
    count = int(math.ceil(horizon / spec.refractory))
    if count > 512:
        raise ValueError("finite expansion exceeds 512 events")
    index = np.arange(count, dtype=float)
    return distance + index * spec.reset, index * spec.refractory


def _refractory_features(spec, distances, shifts, horizon, decays):
    upper = np.maximum(0.0, horizon - shifts)
    lower = np.maximum(0.0, upper - spec.refractory)
    hi = first_passage(distances[:, None], spec.mu, spec.sigma, upper[:, None], decays[None, :])
    lo = first_passage(distances[:, None], spec.mu, spec.sigma, lower[:, None], decays[None, :])
    log_interval = _log_interval(hi["log_H"], lo["log_H"])
    return np.sum(np.exp(log_interval - decays[None, :] *
                         (shifts[:, None] + spec.refractory - horizon)), axis=0)


def operator_features(spec, distance, horizon, *, active_decays=(0.0, 0.5, 1.0, 2.0),
                      refractory_decays=(0.0, 1.0, 3.0), pending_refractory=0.0,
                      quadrature_order=96):
    """Propagate a bounded linear payoff basis and constant running/event costs.

    Feature order is active exp(-z*x), followed by refractory exp(-h*eta).
    The eta>0 state is held at reset and cannot emit. At eta=0 it is active.
    Starting at distance zero emits an immediate event, including at time zero.
    Terminal values are after reset/refractory processing of any prior event.
    Coefficients are constant for this segment; changes require composition.
    """
    x, t, eta = float(distance), float(horizon), float(pending_refractory)
    az, rz = np.asarray(active_decays, float), np.asarray(refractory_decays, float)
    if (not all(math.isfinite(v) for v in (x, t, eta)) or x < 0 or t < 0 or eta < 0
            or eta > spec.refractory or az.ndim != 1 or rz.ndim != 1
            or not np.isfinite(az).all() or not np.isfinite(rz).all()
            or np.any(az < 0) or np.any(rz < 0)):
        raise ValueError("invalid active/refractory state or payoff basis")
    if eta > 0 and not math.isclose(x, spec.reset, rel_tol=0, abs_tol=1e-12):
        raise ValueError("refractory state must be held at the reset distance")
    if type(quadrature_order) is not int or not 16 <= quadrature_order <= 1024:
        raise ValueError("quadrature order must be an integer in [16,1024]")
    if x == 0 and eta == 0:
        result = operator_features(spec, spec.reset, t, active_decays=az,
                                   refractory_decays=rz, pending_refractory=spec.refractory,
                                   quadrature_order=quadrature_order)
        result["expected_events"] += 1.0
        result["discounted_events"] += 1.0
        result["renewal_terms"] += 1
        return result
    discount_t = math.exp(-spec.discount * t)
    if eta > t:
        features = np.r_[np.zeros(len(az)), np.exp(-rz * (eta - t))]
        return {"features": features, "discounted_features": discount_t * features,
                "active_mass": 0.0, "refractory_mass": 1.0, "expected_events": 0.0,
                "discounted_events": 0.0, "discounted_active_time": 0.0,
                "mass_quadrature_defect": 0.0, "renewal_terms": 0}
    if eta > 0:
        result = operator_features(spec, spec.reset, t - eta, active_decays=az,
                                   refractory_decays=rz, quadrature_order=quadrature_order)
        factor = math.exp(-spec.discount * eta)
        result["discounted_features"] *= factor
        result["discounted_events"] *= factor
        result["discounted_active_time"] *= factor
        return result
    if t == 0:
        features = np.r_[np.exp(-az * x), np.zeros(len(rz))]
        return {"features": features, "discounted_features": features.copy(),
                "active_mass": 1.0, "refractory_mass": 0.0, "expected_events": 0.0,
                "discounted_events": 0.0, "discounted_active_time": 0.0,
                "mass_quadrature_defect": 0.0, "renewal_terms": 0}
    distances, shifts = _renewal_terms(spec, x, t)
    upper = t - shifts
    lower = np.maximum(0.0, upper - spec.refractory)
    hit = first_passage(distances, spec.mu, spec.sigma, upper, spec.discount)
    earlier = first_passage(distances, spec.mu, spec.sigma, lower, spec.discount)
    ref_mass = float(np.sum(hit["F"] - earlier["F"]))
    active_mass = 1.0 - ref_mass
    if not -1e-11 <= active_mass <= 1.0 + 1e-11:
        raise ArithmeticError("renewal mass is outside probability bounds")
    nodes, weights = _quadrature_rule(quadrature_order)
    active = np.asarray(killed_laplace(x, spec.mu, spec.sigma, t, az))
    quadrature_mass = float(first_passage(x, spec.mu, spec.sigma, t)["S"])
    widths = t - shifts - spec.refractory
    eligible = widths > 0
    widths = widths[eligible]
    if len(widths):
        times = widths[:, None] * (nodes[None, :] + 1) / 2
        density = first_passage(distances[eligible, None], spec.mu, spec.sigma, times)["f"]
        weight = widths[:, None] * weights[None, :] * density / 2
        left = widths[:, None] - times
        values = killed_laplace(spec.reset, spec.mu, spec.sigma,
                                left[:, :, None], az[None, None, :])
        active += np.sum(weight[:, :, None] * values, axis=(0, 1))
        quadrature_mass += float(np.sum(weight * first_passage(
            spec.reset, spec.mu, spec.sigma, left)["S"]))
    # For the constant payoff, use the known mass exactly and report the raw
    # quadrature defect separately. Other payoffs retain quadrature error.
    active = np.where(az == 0, active_mass, active)
    refractory = _refractory_features(spec, distances, shifts, t, rz)
    discounted_events = float(np.sum(np.exp(-spec.discount * shifts) * hit["H"]))
    if spec.discount == 0:
        times = (upper + lower)[:, None] / 2 + (upper - lower)[:, None] * nodes[None, :] / 2
        probabilities = first_passage(distances[:, None], spec.mu, spec.sigma, times)["F"]
        lost_time = float(np.sum((upper - lower) * (probabilities @ weights) / 2))
        active_time = t - lost_time
    elif spec.discount >= 1e-5:
        q = spec.discount
        refractory_time = float(np.sum(
            np.exp(-q * shifts) * (hit["H"] - math.exp(-q * spec.refractory) * earlier["H"])
            - math.exp(-q * t) * (hit["F"] - earlier["F"]))) / q
        active_time = -math.expm1(-q * t) / q - refractory_time
    else:
        # This small-q branch avoids a cancellation of three O(1) terms.
        def integrand(u):
            hi = np.maximum(0.0, u - shifts)
            lo = np.maximum(0.0, hi - spec.refractory)
            probability = np.sum(first_passage(distances, spec.mu, spec.sigma, hi)["F"]
                                 - first_passage(distances, spec.mu, spec.sigma, lo)["F"])
            return math.exp(-spec.discount * u) * (1.0 - probability)
        active_time = quad(integrand, 0.0, t, epsabs=2e-11, epsrel=2e-11,
                           points=list(shifts[shifts < t]), limit=1024)[0]
    features = np.r_[active, refractory]
    return {"features": features, "discounted_features": discount_t * features,
            "active_mass": active_mass, "refractory_mass": ref_mass,
            "expected_events": float(np.sum(hit["F"])),
            "discounted_events": discounted_events, "discounted_active_time": active_time,
            "mass_quadrature_defect": quadrature_mass - active_mass,
            "renewal_terms": len(distances)}


def apply_value(features, payoff_weights, *, running_reward=0.0, event_reward=0.0):
    """Linear value layer; its exact weight gradient is discounted_features."""
    weights = np.asarray(payoff_weights, float)
    if weights.shape != features["discounted_features"].shape or not np.isfinite(weights).all():
        raise ValueError("finite payoff weights matching the terminal basis required")
    if not math.isfinite(running_reward) or not math.isfinite(event_reward):
        raise ValueError("finite reward coefficients required")
    return float(features["discounted_features"] @ weights
                 + running_reward * features["discounted_active_time"]
                 + event_reward * features["discounted_events"])
