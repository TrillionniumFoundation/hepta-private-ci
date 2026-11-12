"""Boundary-graded CTMC used by the actual joint deterministic-delay solver.

The mesh is fixed before each episode. It changes the discrete model; it is
not adaptive posterior rebinning. The upper state remains nonreturning.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import eigh_tridiagonal, solve_banded

from qualification.hcsn_boundary_audit.spatial_generator import (
    KilledSpatialGenerator,
    _real,
)


@dataclass(frozen=True)
class GradedSpatialGenerator(KilledSpatialGenerator):
    grading: float = 6.0

    def __post_init__(self):
        if type(self.intervals) is not int or not 4 <= self.intervals <= 512:
            raise ValueError("intervals must be an integer in [4,512]")
        for name in ("endpoint", "mu", "sigma", "grading"):
            _real(name, getattr(self, name), positive=name in ("endpoint", "sigma"))
        if (
            not 0.001 <= self.endpoint <= 8
            or abs(self.mu) > 2
            or not 0.05 <= self.sigma <= 2
            or not 0 <= self.grading <= 6
        ):
            raise ValueError("outside declared graded-generator research domain")
        if any(not np.isfinite(a).all() or np.min(a) <= 0 for a in self.rates):
            raise ValueError("strictly positive rates required; refine grid")

    @property
    def spacing(self):
        raise TypeError("nonuniform mesh has no scalar spacing; use nodes")

    @property
    def nodes(self):
        if self.grading == 0:
            return np.linspace(0, self.endpoint, self.intervals + 1)
        return (
            self.endpoint
            * np.expm1(self.grading * np.arange(self.intervals + 1) / self.intervals)
            / math.expm1(self.grading)
        )

    @property
    def rates(self):
        widths = np.diff(self.nodes)
        left, right = widths[:-1], widths[1:]
        return (
            (self.sigma**2 - self.mu * right) / (left * (left + right)),
            (self.sigma**2 + self.mu * left) / (right * (left + right)),
        )

    def matrix(self):
        down, up = self.rates
        matrix = np.zeros((self.intervals + 1, self.intervals + 1))
        i = np.arange(1, self.intervals)
        matrix[i, i - 1], matrix[i, i], matrix[i, i + 1] = down, -down - up, up
        return matrix

    def _solve(self, discount, rhs):
        down, up = self.rates
        band = np.zeros((3, self.intervals - 1))
        band[0, 1:], band[1], band[2, :-1] = -up[:-1], discount + down + up, -down[1:]
        return solve_banded((1, 1), band, rhs)

    def discounted_lower_hit(self, discount):
        discount = _real("discount", discount, positive=True)
        if not 0.001 <= discount <= 4:
            raise ValueError("discount outside declared domain")
        rhs = np.zeros(self.intervals - 1)
        rhs[0] = self.rates[0][0]
        values = np.r_[1.0, self._solve(discount, rhs), 0.0]
        if not np.isfinite(values).all() or values.min() < 0 or values.max() > 1:
            raise ArithmeticError("unresolved discounted-hit solve")
        return values

    def lower_hit_partials(self, discount):
        raise NotImplementedError(
            "uniform-grid derivatives are not graded-grid gradients"
        )


class ShortGapKernel:
    """Spectral first-excursion M/H/A, used only for horizons <= delay.

    Algebraically the same CTMC as JointModel, independently evaluated without
    DDE interpolation. Initial refractory releases use exact integral kernels.
    This does not implement continuation beyond one delay or observation update.
    """

    def __init__(self, spatial, discount):
        self.spatial, self.discount = (
            spatial,
            _real("discount", discount, positive=True),
        )
        down, up = spatial.rates
        self.scale = np.exp(np.r_[0.0, np.cumsum(0.5 * np.log(up[:-1] / down[1:]))])
        self.eigen, self.vectors = eigh_tridiagonal(
            -(down + up), np.sqrt(up[:-1] * down[1:])
        )
        force = np.zeros(spatial.intervals - 1)
        force[0] = down[0]
        self.coefficient = self.vectors.T @ (self.scale * force)
        if self.eigen.max() >= 0 or not np.isfinite(self.scale).all():
            raise ArithmeticError("unresolved reversible transient generator")
        self.cache = {}

    def at(self, duration):
        t = _real("duration", duration)
        if not 0 <= t <= 2:
            raise ValueError("finite nonnegative short duration required")
        if t not in self.cache:
            rate, q = self.eigen, self.discount

            def project(coeff):
                return self.vectors @ (self.coefficient * coeff) / self.scale

            f = np.r_[1.0, project(np.expm1(rate * t) / rate), 0.0]
            g = np.r_[1.0, project(np.expm1((rate - q) * t) / (rate - q)), 0.0]
            z = rate * t
            jgain = np.empty_like(z)
            small = abs(z) < 1e-3
            w = z[small]
            jgain[small] = t * t * (0.5 + w / 6 + w * w / 24 + w**3 / 120 + w**4 / 720)
            jgain[~small] = (np.expm1(z[~small]) - z[~small]) / rate[~small] ** 2
            j = np.r_[t, project(jgain), 0.0]
            a = -math.expm1(-q * t) / q - (g - math.exp(-q * t) * f) / q
            a[0] = 0.0  # The lower cemetery has zero active reward.
            self.cache[t] = (f, g, a, j)
        return self.cache[t]

    def basis(self, model, weights, duration, phase_cells=8):
        if model.spatial != self.spatial or model.discount != self.discount:
            raise ValueError("kernel/model mismatch")
        if not 0 <= duration <= model.delay:
            raise ValueError("a fresh hit cannot reenter inside this kernel")
        f, g, a, _ = self.at(duration)
        rows = [*(weights @ np.stack((f, g, a), axis=-1))]
        q = self.discount
        for left, right in zip(
            np.linspace(0, model.delay, phase_cells + 1)[:-1],
            np.linspace(0, model.delay, phase_cells + 1)[1:],
        ):
            if left >= duration:
                rows.append(np.zeros(3))
                continue
            lo, hi = max(0.0, duration - right), duration - left
            fl, gl, _, jl = self.at(lo)
            fh, gh, _, jh = self.at(hi)
            integral = ((math.exp(q * hi) * gh - fh) - (math.exp(q * lo) * gl - fl)) / q
            mass = (jh - jl) / (right - left)
            hit = math.exp(-q * duration) * integral / (right - left)
            exp_integral = math.exp(q * lo) * math.expm1(q * (hi - lo)) / q
            active = (
                math.exp(-q * duration)
                * (exp_integral - (hi - lo) - integral + jh - jl)
                / (q * (right - left))
            )
            rows.append(
                [
                    np.interp(model.reset, self.spatial.nodes, v)
                    for v in (mass, hit, active)
                ]
            )
        return np.asarray(rows)
