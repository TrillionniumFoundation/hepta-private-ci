"""Verified perpetual affine-payoff stopping benchmark; no learned efficacy."""

from dataclasses import dataclass

import numpy as np

from .roots import DiffusionRoots, stable_roots, validate_finite


@dataclass(frozen=True)
class OneShotSolution:
    mu: float
    sigma: float
    discount: float
    killing: float
    cost: float
    roots: DiffusionRoots
    boundary: float
    unconstrained_boundary: float
    regime: str
    boundary_derivatives: dict[str, float]

    def value(self, state):
        """Payoff of this threshold policy, with immediate action above it."""
        state = np.asarray(state, dtype=float)
        continuation = (self.boundary - self.cost) * np.exp(
            -self.roots.kappa * np.maximum(self.boundary - state, 0.0)
        )
        return np.where(state < self.boundary, continuation, state - self.cost)

    def derivative_x(self, state):
        state = np.asarray(state, dtype=float)
        return np.where(
            state < self.boundary, self.roots.kappa * self.value(state), 1.0
        )

    def value_sensitivities(self, state):
        """Total value derivatives, including the re-solved optimal boundary."""
        state = np.asarray(state, dtype=float)
        gap = np.maximum(self.boundary - state, 0.0)
        q = np.exp(-self.roots.kappa * gap)
        reward = self.boundary - self.cost
        output = {}
        for key, db in self.boundary_derivatives.items():
            root_key = "rate" if key in {"discount", "killing"} else key
            dk = self.roots.kappa_derivatives.get(root_key, 0.0)
            below = q * (
                db - (key == "cost") - reward * (gap * dk + self.roots.kappa * db)
            )
            output[key] = np.where(state < self.boundary, below, -float(key == "cost"))
        return output

    def generator_residual(self, state):
        """Classical (L-r)V off the boundary; constrained kinks are excluded."""
        state = np.asarray(state, dtype=float)
        return np.where(
            state < self.boundary,
            0.0,
            self.mu - (self.discount + self.killing) * self.value(state),
        )


def one_shot_solution(mu, sigma, discount, cost, *, killing=0.0, bounds=None):
    """Solve sup E[e^(-rho*tau)(X_tau-cost) 1(tau<kill)].

    The exact unconstrained solution has boundary cost+1/kappa. Optional
    absolute boundary bounds optimize over the restricted threshold family;
    an active bound is NOT a free-boundary smooth-fit solution. Bounds must
    leave a positive-payoff threshold available. Zero total rate is rejected
    because that is a separate, sometimes unbounded, stopping problem.
    """
    validate_finite(mu=mu, sigma=sigma, discount=discount, killing=killing, cost=cost)
    if discount < 0 or killing < 0 or discount + killing <= 0:
        raise ValueError(
            "discount/killing nonnegative and positive total rate required"
        )
    roots = stable_roots(mu, sigma, discount + killing)
    k = roots.kappa
    candidate = float(cost + 1.0 / k)
    boundary, regime = candidate, "interior"
    derivatives = {
        "mu": 1.0 / (k * roots.delta),
        "sigma": sigma / roots.delta,
        "discount": -1.0 / (k * k * roots.delta),
        "killing": -1.0 / (k * k * roots.delta),
        "cost": 1.0,
    }
    if bounds is not None:
        lower, upper = map(float, bounds)
        validate_finite(lower=lower, upper=upper)
        if lower > upper or upper <= cost:
            raise ValueError(
                "bounds must be ordered and admit a positive-payoff threshold"
            )
        boundary = min(max(candidate, lower), upper)
        if boundary != candidate:
            regime = "lower_bound" if boundary == lower else "upper_bound"
            derivatives = dict.fromkeys(derivatives, 0.0)
    return OneShotSolution(
        float(mu),
        float(sigma),
        float(discount),
        float(killing),
        float(cost),
        roots,
        boundary,
        candidate,
        regime,
        derivatives,
    )
