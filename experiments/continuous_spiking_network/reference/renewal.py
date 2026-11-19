"""Repeated affine rewards with reset and refractory delay.

This model has no cancellation or silent Poisson reset. Adding either changes
its renewal equation; a discount must not be renamed an event probability.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import lambertw

from .roots import stable_roots, validate_finite


def _exp_remainder(x):
    if abs(x) >= 1e-4:
        return math.expm1(-x) + x
    return x * x * (0.5 + x * (-1 / 6 + x * (1 / 24 + x * (-1 / 120 + x / 720))))


def _dimensionless_boundary(m, delay, method):
    """Solve z-m-1+exp(-delay-z)=0 for the positive interior root."""
    epsilon = m + delay
    if method == "brent":

        def equation(z):
            return _exp_remainder(delay + z) - epsilon

        upper = max(1.0, m + 2.0)
        while equation(upper) <= 0:
            upper *= 2.0
        return brentq(equation, 0.0, upper, xtol=1e-15, rtol=1e-14)
    if method != "lambertw":
        raise ValueError("method must be 'lambertw' or 'brent'")
    if epsilon < 1e-5:
        p = math.sqrt(-2.0 * math.expm1(-epsilon))
        one_plus_w = p * (
            1
            + p
            * (
                -1 / 3
                + p * (11 / 72 + p * (-43 / 540 + p * (769 / 17280 - p * 221 / 8505)))
            )
        )
    else:
        one_plus_w = 1.0 + float(lambertw(-math.exp(-1.0 - epsilon), 0).real)
    return m + one_plus_w


@dataclass(frozen=True)
class RenewalSolution:
    mu: float
    sigma: float
    discount: float
    reset: float
    cost: float
    refractory: float
    kappa: float
    delta: float
    boundary: float
    regime: str
    reset_value: float
    condition_index: float
    boundary_derivatives: dict[str, float]
    value_derivatives: dict[str, float]

    def value(self, state):
        if self.regime in {"unbounded", "chattering_supremum"}:
            raise ValueError("no admissible attaining threshold for " + self.regime)
        state = np.asarray(state, dtype=float)
        if self.regime == "abstain":
            return np.zeros_like(state)
        amplitude = self.boundary - self.cost + self.delta * self.reset_value
        below = amplitude * np.exp(-self.kappa * np.maximum(self.boundary - state, 0.0))
        return np.where(
            state < self.boundary,
            below,
            state - self.cost + self.delta * self.reset_value,
        )

    def derivative_x(self, state):
        state = np.asarray(state, dtype=float)
        if self.regime == "abstain":
            return np.zeros_like(state)
        return np.where(state < self.boundary, self.kappa * self.value(state), 1.0)

    def value_sensitivities(self, state):
        """Whole-solution derivatives for a future tensor/custom-autograd wrapper."""
        state = np.asarray(state, dtype=float)
        if self.regime in {"unbounded", "chattering_supremum"}:
            raise ValueError("no derivative of an attaining policy for " + self.regime)
        if self.regime == "abstain":
            return {key: np.zeros_like(state) for key in self.boundary_derivatives}
        roots = stable_roots(self.mu, self.sigma, self.discount)
        gap = np.maximum(self.boundary - state, 0.0)
        q = np.exp(-self.kappa * gap)
        amplitude = self.boundary - self.cost + self.delta * self.reset_value
        output = {}
        for key, db in self.boundary_derivatives.items():
            dk = roots.kappa_derivatives.get("rate" if key == "discount" else key, 0.0)
            d_delta = -self.delta * (
                self.refractory * (key == "discount")
                + self.discount * (key == "refractory")
            )
            action_derivative = (
                -(key == "cost")
                + d_delta * self.reset_value
                + self.delta * self.value_derivatives[key]
            )
            below = q * (
                db + action_derivative - amplitude * (gap * dk + self.kappa * db)
            )
            output[key] = np.where(state < self.boundary, below, action_derivative)
        return output

    def generator_residual(self, state):
        state = np.asarray(state, dtype=float)
        if self.regime == "abstain":
            return np.zeros_like(state)
        return np.where(
            state < self.boundary, 0.0, self.mu - self.discount * self.value(state)
        )


def renewal_objective(boundary, mu, sigma, discount, reset, cost, refractory):
    """Discounted reward of a feasible fixed threshold, including opt-out."""
    validate_finite(boundary=boundary, reset=reset, cost=cost, refractory=refractory)
    if discount <= 0 or refractory < 0 or boundary < reset:
        raise ValueError("positive discount, nonnegative delay and gap required")
    k = stable_roots(mu, sigma, discount).kappa
    log_q = -k * (boundary - reset)
    denominator = -math.expm1(-discount * refractory + log_q)
    if denominator == 0:
        raise ValueError("zero-time repeated intervention is not admissible")
    return max(0.0, math.exp(log_q) * (boundary - cost) / denominator)


def renewal_solution(
    mu,
    sigma,
    discount,
    reset,
    cost,
    refractory,
    *,
    method="lambertw",
    min_gap=0.0,
    max_gap=None,
):
    """Optimize stationary thresholds, with explicit nonattainment regimes.

    Gap bounds are relative to reset. Sensitivities apply within an active set;
    they do not exist across its switching surface. An active bound is a
    restricted threshold solution, not an unconstrained smooth-fit optimum.
    Interior derivatives re-solve the renewal problem, including continuation.
    Active bounds and abstention optimize the threshold family from reset;
    they are not claimed to solve the unconstrained whole-state impulse QVI.
    """
    validate_finite(
        mu=mu,
        sigma=sigma,
        discount=discount,
        reset=reset,
        cost=cost,
        refractory=refractory,
        min_gap=min_gap,
    )
    if discount <= 0 or refractory < 0 or min_gap < 0:
        raise ValueError(
            "positive discount and nonnegative refractory/min_gap required"
        )
    if max_gap is not None:
        validate_finite(max_gap=max_gap)
        if max_gap < min_gap or max_gap <= 0:
            raise ValueError("max_gap must be positive and not below min_gap")
    if method not in {"brent", "lambertw"}:
        raise ValueError("unknown boundary solver")
    roots = stable_roots(mu, sigma, discount)
    k, delay = roots.kappa, discount * refractory
    delta, m = math.exp(-delay), k * (cost - reset)
    has_interior = m > math.expm1(-delay)
    if has_interior:
        gap = _dimensionless_boundary(m, delay, method) / k
        regime = "interior"
    else:
        gap, regime = 0.0, "immediate_after_refractory"
    if gap < min_gap:
        gap, regime = min_gap, "lower_bound"
    if max_gap is not None and gap > max_gap:
        gap, regime = max_gap, "upper_bound"
    boundary = reset + gap
    keys = ("mu", "sigma", "discount", "reset", "cost", "refractory")
    if gap == 0.0 and delay == 0.0:
        regime = "unbounded" if cost < reset else "chattering_supremum"
        value = math.inf if cost < reset else 1.0 / k
        return RenewalSolution(
            mu,
            sigma,
            discount,
            reset,
            cost,
            refractory,
            k,
            delta,
            boundary,
            regime,
            value,
            math.inf,
            {},
            {},
        )
    if boundary <= cost:
        return RenewalSolution(
            mu,
            sigma,
            discount,
            reset,
            cost,
            refractory,
            k,
            delta,
            boundary,
            "abstain",
            0.0,
            0.0,
            dict.fromkeys(keys, 0.0),
            dict.fromkeys(keys, 0.0),
        )
    q = math.exp(-k * gap)
    s = math.exp(-delay - k * gap)
    denominator = -math.expm1(-delay - k * gap)
    reward, value = boundary - cost, q * (boundary - cost) / denominator
    if regime == "interior":
        coefficient = reward - s * gap
        equation_derivatives = {
            "mu": coefficient * roots.kappa_derivatives["mu"],
            "sigma": coefficient * roots.kappa_derivatives["sigma"],
            "discount": coefficient / roots.delta - refractory * s,
            "reset": k * s,
            "cost": -k,
            "refractory": -discount * s,
        }
        db = {key: -v / (k * denominator) for key, v in equation_derivatives.items()}
    else:
        db = dict.fromkeys(keys, 0.0)
        db["reset"] = 1.0  # Fixed relative gap / immediate release action.
    dv = {}
    for key in keys:
        dk = roots.kappa_derivatives.get("rate" if key == "discount" else key, 0.0)
        dq = q * (-gap * dk - k * (db[key] - float(key == "reset")))
        d_delta = -delta * (
            refractory * (key == "discount") + discount * (key == "refractory")
        )
        d_denom = -d_delta * q - delta * dq
        dv[key] = (
            dq * reward + q * (db[key] - (key == "cost"))
        ) / denominator - value * d_denom / denominator
    return RenewalSolution(
        mu,
        sigma,
        discount,
        reset,
        cost,
        refractory,
        k,
        delta,
        boundary,
        regime,
        value,
        1.0 / denominator,
        db,
        dv,
    )
