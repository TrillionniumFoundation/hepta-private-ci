"""New fixed graded spatial candidate; original uniform-grid evidence is separate."""

from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import solve_banded


@dataclass(frozen=True)
class GradedSpatialGenerator:
    intervals: int
    endpoint: float
    mu: float
    sigma: float
    stretch: float = 6.0

    def __post_init__(self):
        if type(self.intervals) is not int or not 4 <= self.intervals <= 1024:
            raise ValueError("interval count outside research domain")
        for name in ("endpoint", "mu", "sigma", "stretch"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("finite fixed scalar geometry/physics required")
        if (
            not 0.001 <= self.endpoint <= 8
            or not abs(self.mu) <= 2
            or not 0.05 <= self.sigma <= 2
            or not 0 <= self.stretch <= 12
        ):
            raise ValueError("graded research parameter domain exceeded")
        down, up = self.rates
        if (
            not np.isfinite(down).all()
            or not np.isfinite(up).all()
            or min(down.min(), up.min()) < 0
        ):
            raise ValueError("negative/nonfinite rates; refine the fixed geometry")

    @property
    def nodes(self):
        unit = np.linspace(0.0, 1.0, self.intervals + 1)
        result = self.endpoint * (
            unit
            if self.stretch == 0
            else np.expm1(self.stretch * unit) / math.expm1(self.stretch)
        )
        result.setflags(write=False)
        return result

    @property
    def rates(self):
        gaps = np.diff(self.nodes)
        left, right = gaps[:-1], gaps[1:]
        down = (self.sigma**2 - self.mu * right) / (left * (left + right))
        up = (self.sigma**2 + self.mu * left) / (right * (left + right))
        return down, up

    def matrix(self):
        down, up = self.rates
        result = np.zeros((self.intervals + 1, self.intervals + 1))
        rows = np.arange(1, self.intervals)
        result[rows, rows - 1] = down
        result[rows, rows + 1] = up
        result[rows, rows] = -(down + up)
        return result

    def discounted_lower_hit(self, discount):
        if (
            isinstance(discount, bool)
            or not isinstance(discount, (int, float))
            or not 0.001 <= discount <= 4
        ):
            raise ValueError("qualified finite positive discount required")
        down, up = self.rates
        band = np.zeros((3, self.intervals - 1))
        band[0, 1:] = -up[:-1]
        band[1] = discount + down + up
        band[2, :-1] = -down[1:]
        rhs = np.zeros(self.intervals - 1)
        rhs[0] = down[0]
        values = np.r_[1.0, solve_banded((1, 1), band, rhs), 0.0]
        if not np.isfinite(values).all() or values.min() < 0 or values.max() > 1:
            raise ArithmeticError("unresolved graded discounted hit transform")
        return values
