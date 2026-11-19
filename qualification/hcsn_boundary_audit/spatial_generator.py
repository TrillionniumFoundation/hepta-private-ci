"""Research-only killed spatial CTMC; not the HCSN returning-tail/reset model.

State nodes are 0,h,...,L. Both endpoints absorb, with lower-hit and upper-exit
kept distinct. A fixed birth/death generator evolves nodal masses without
reconstructing a uniform density after each observation interval.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import expm, solve_banded


def _real(name, value, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite real")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"invalid {name}")
    return float(value)


@dataclass(frozen=True)
class KilledSpatialGenerator:
    """One immutable constant-physics finite-domain research generator.

    Central rates are accepted only when both are nonnegative. No clipping,
    normalization or drift-dependent change of scheme is performed.
    """

    intervals: int
    endpoint: float
    mu: float
    sigma: float

    def __post_init__(self):
        if type(self.intervals) is not int or not 4 <= self.intervals <= 512:
            raise ValueError("intervals must be an integer in [4,512]")
        for name in ("endpoint", "mu", "sigma"):
            _real(name, getattr(self, name), positive=name != "mu")
        if (
            not 0.001 <= self.endpoint <= 8
            or not abs(self.mu) <= 2
            or not 0.05 <= self.sigma <= 2
        ):
            raise ValueError(
                "research domain requires L in [.001,8], |mu|<=2, sigma in [.05,2]"
            )
        if not all(math.isfinite(x) and x >= 0 for x in self.rates):
            raise ValueError("nonfinite or negative jump rate: refine the spatial grid")

    @property
    def spacing(self):
        return self.endpoint / self.intervals

    @property
    def nodes(self):
        return np.linspace(0, self.endpoint, self.intervals + 1)

    @property
    def rates(self):
        h = self.spacing
        diffusion = (self.sigma / h) ** 2 / 2
        advection = self.mu / (2 * h)
        return diffusion - advection, diffusion + advection

    def matrix(self):
        n, (down, up) = self.intervals, self.rates
        result = np.zeros((n + 1, n + 1), dtype=np.float64)
        indices = np.arange(1, n)
        result[indices, indices - 1] = down
        result[indices, indices + 1] = up
        result[indices, indices] = -(down + up)
        return result

    def transition(self, duration):
        duration = _real("duration", duration)
        if not 0 <= duration <= 2:
            raise ValueError("research duration must be in [0,2]")
        # expm on the full generator retains the two separate absorbing states.
        result = expm(duration * self.matrix())
        if not np.all(np.isfinite(result)):
            raise ArithmeticError("unresolved transition exponential")
        return result

    def _solve(self, discount, rhs):
        n, (down, up) = self.intervals, self.rates
        band = np.zeros((3, n - 1), dtype=np.float64)
        band[0, 1:] = -up
        band[1] = discount + down + up
        band[2, :-1] = -down
        return solve_banded((1, 1), band, rhs)

    def discounted_lower_hit(self, discount):
        """E[exp(-q*tau0); tau0<tauL] at all nodes, including endpoints."""
        discount = _real("discount", discount, positive=True)
        if not 0.001 <= discount <= 4:
            raise ValueError("research discount must be in [.001,4]")
        rhs = np.zeros(self.intervals - 1)
        rhs[0] = self.rates[0]
        values = np.concatenate(([1.0], self._solve(discount, rhs), [0.0]))
        if not np.all(np.isfinite(values)) or np.min(values) < 0 or np.max(values) > 1:
            raise ArithmeticError("unresolved discounted-hit solve")
        return values

    def lower_hit_partials(self, discount):
        """Implicit derivatives of this discrete solve, not continuum/AD evidence."""
        discount = _real("discount", discount, positive=True)
        if min(self.rates) <= 0:
            raise ValueError(
                "two-sided physical partials require strictly positive rates"
            )
        values = self.discounted_lower_hit(discount)
        h = self.spacing
        rhs_mu = (values[2:] - values[:-2]) / (2 * h)
        rhs_sigma = self.sigma * (values[:-2] - 2 * values[1:-1] + values[2:]) / h**2
        return {
            name: np.concatenate(([0.0], self._solve(discount, rhs), [0.0]))
            for name, rhs in (
                ("mu", rhs_mu),
                ("sigma", rhs_sigma),
                ("discount", -values[1:-1]),
            )
        }


def continuum_lower_hit(nodes, endpoint, mu, sigma, discount):
    """Closed-form finite-interval BVP: L phi=q phi, phi(0)=1, phi(L)=0.

    This reference has a real upper killing boundary, not a returning tail.
    Stable exponential differences avoid sinh overflow.
    """
    endpoint = _real("endpoint", endpoint, positive=True)
    mu = _real("mu", mu)
    sigma = _real("sigma", sigma, positive=True)
    discount = _real("discount", discount, positive=True)
    if not 0.001 <= endpoint <= 8 or not abs(mu) <= 2 or not 0.05 <= sigma <= 2:
        raise ValueError("reference is outside the declared research physics domain")
    if not 0.001 <= discount <= 4:
        raise ValueError("research discount must be in [.001,4]")
    x = np.asarray(nodes, dtype=np.float64)
    if not np.all(np.isfinite(x)) or np.any(x < 0) or np.any(x > endpoint):
        raise ValueError("nodes must lie in the finite interval")
    kappa = math.hypot(mu, math.sqrt(2 * discount) * sigma)
    beta = kappa / sigma**2
    # Stable positive half-line Laplace exponent, including negative drift.
    alpha = (mu + kappa) / sigma**2 if mu >= 0 else 2 * discount / (kappa - mu)
    return (
        np.exp(-alpha * x)
        * -np.expm1(-2 * beta * (endpoint - x))
        / -math.expm1(-2 * beta * endpoint)
    )
