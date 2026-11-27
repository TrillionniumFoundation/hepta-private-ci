"""Bounded real-surrogate QVI inversion; no network/torch/filesystem access.

This module is an unexecuted research proposal. It never asserts that its real
root is attained by the F32 recurrent model. Every unresolved branch abstains.
Decimal exp/sqrt are correctly rounded by the standard decimal contract; one
adjacent Decimal on either side encloses that rounded result. All arithmetic
uses explicit outward rounding. Call and wall budgets include rejected cells.
"""

from dataclasses import dataclass, field
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext
import math
import time


PRECISION = 64
ZERO = Decimal(0)
ONE = Decimal(1)


class Abstain(ValueError):
    """The fixed proposal cannot certify a permissible candidate."""


def exact(value):
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        result = Decimal.from_float(value)
    else:
        result = Decimal(value)
    if not result.is_finite():
        raise Abstain("NONFINITE_DECIMAL_INPUT")
    return result


def rounded(operation, direction):
    with localcontext() as context:
        context.prec = PRECISION
        context.rounding = direction
        context.Emax = 999
        context.Emin = -999
        value = operation()
        if not value.is_finite():
            raise Abstain("DECIMAL_OVERFLOW")
        return value


@dataclass(frozen=True)
class Interval:
    lo: Decimal
    hi: Decimal

    def __post_init__(self):
        if not self.lo.is_finite() or not self.hi.is_finite() or self.lo > self.hi:
            raise Abstain("INVALID_INTERVAL")

    @classmethod
    def point(cls, value):
        value = exact(value)
        return cls(value, value)

    @staticmethod
    def coerce(value):
        return value if isinstance(value, Interval) else Interval.point(value)

    def __add__(self, other):
        other = self.coerce(other)
        return Interval(rounded(lambda: self.lo + other.lo, ROUND_FLOOR),
                        rounded(lambda: self.hi + other.hi, ROUND_CEILING))

    __radd__ = __add__

    def __neg__(self):
        # Decimal.copy_negate is exact and does not use the caller's context.
        return Interval(self.hi.copy_negate(), self.lo.copy_negate())

    def __sub__(self, other):
        return self + -self.coerce(other)

    def __rsub__(self, other):
        return self.coerce(other) + -self

    def __mul__(self, other):
        other = self.coerce(other)
        pairs = [(x, y) for x in (self.lo, self.hi) for y in (other.lo, other.hi)]
        return Interval(min(rounded(lambda x=x, y=y: x*y, ROUND_FLOOR) for x, y in pairs),
                        max(rounded(lambda x=x, y=y: x*y, ROUND_CEILING) for x, y in pairs))

    __rmul__ = __mul__

    def reciprocal(self):
        if self.lo <= ZERO <= self.hi:
            raise Abstain("INTERVAL_DIVISION_THROUGH_ZERO")
        return Interval(rounded(lambda: ONE/self.hi, ROUND_FLOOR),
                        rounded(lambda: ONE/self.lo, ROUND_CEILING))

    def __truediv__(self, other):
        return self * self.coerce(other).reciprocal()

    def __rtruediv__(self, other):
        return self.coerce(other) * self.reciprocal()

    def square(self):
        if self.lo <= ZERO <= self.hi:
            upper = max(self.lo.copy_abs(), self.hi.copy_abs())
            return Interval(ZERO, rounded(lambda: upper*upper, ROUND_CEILING))
        values = (self.lo.copy_abs(), self.hi.copy_abs())
        lower, upper = min(values), max(values)
        return Interval(rounded(lambda: lower*lower, ROUND_FLOOR),
                        rounded(lambda: upper*upper, ROUND_CEILING))

    def _monotone_transcendental(self, name):
        if name == "sqrt" and self.lo < ZERO:
            raise Abstain("SQRT_NEGATIVE_INTERVAL")
        with localcontext() as context:
            context.prec = PRECISION
            context.rounding = ROUND_HALF_EVEN
            lower = getattr(self.lo, name)()
            upper = getattr(self.hi, name)()
            if not lower.is_finite() or not upper.is_finite():
                raise Abstain("TRANSCENDENTAL_OVERFLOW")
            lo = lower.next_minus(context)
            hi = upper.next_plus(context)
            # Both functions are nonnegative; zero may be exact.
            return Interval(max(ZERO, lo), hi)

    def sqrt(self):
        return self._monotone_transcendental("sqrt")

    def exp(self):
        return self._monotone_transcendental("exp")

    def tanh(self):
        # tanh is monotone, so endpoint evaluation avoids dependency widening.
        def at(value):
            e = (Interval.point(value)*2).exp()
            return (e-1)/(e+1)
        return Interval(max(-ONE, at(self.lo).lo), min(ONE, at(self.hi).hi))

    def sign(self):
        return 1 if self.lo > ZERO else -1 if self.hi < ZERO else 0

    def absolute(self):
        if self.lo <= ZERO <= self.hi:
            return Interval(ZERO, max(self.lo.copy_abs(), self.hi.copy_abs()))
        values = (self.lo.copy_abs(), self.hi.copy_abs())
        return Interval(min(values), max(values))

    def width(self):
        return rounded(lambda: self.hi-self.lo, ROUND_CEILING)

    def midpoint(self):
        return rounded(lambda: (self.lo+self.hi)/2, ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Constants:
    mu0: float
    drift_scale: float
    cost0: float
    cost_span: float
    sigma: float
    rho: float
    eta: float
    gain: float
    maintenance: float
    cost_drive: float = .15

    def validate(self):
        values = tuple(vars(self).values())
        if not all(math.isfinite(value) for value in values):
            raise Abstain("NONFINITE_PHYSICAL_CONSTANT")
        if not (self.sigma > 0 and self.rho > 0 and self.gain > 0
                and 0 < self.eta < 1 and self.drift_scale > 0
                and self.cost_span > 0 and self.cost_drive > 0):
            raise Abstain("PHYSICAL_DOMAIN")


@dataclass
class Ledger:
    deadline: float
    cells: int = 0
    bisections: int = 0
    interval_evaluations: int = 0
    point_evaluations: int = 0
    discarded_cells: int = 0
    subdivisions: int = 0
    monotone_cells: int = 0
    partition: list = field(default_factory=list)
    roots: list = field(default_factory=list)

    def check_time(self):
        if time.monotonic() > self.deadline:
            raise Abstain("SCALAR_INVERSE_DEADLINE")


def residual_and_derivative(z, boundary, absolute, theta, constants, ledger):
    """Outward F and dF/dz, retaining the drive/cost coupling."""
    ledger.check_time()
    if z.lo == z.hi:
        ledger.point_evaluations += 1
    else:
        ledger.interval_evaluations += 1
    p = {name: Interval.point(value) for name, value in vars(constants).items()}
    b, a, theta = map(Interval.point, (boundary, absolute, theta))
    t = z.tanh()
    tc = (theta + p["cost_drive"]*z).tanh()
    mu = p["mu0"] + p["drift_scale"]*t
    cost = p["cost0"] + p["cost_span"]*tc
    r = (mu.square() + 2*p["rho"]*p["sigma"].square()).sqrt()
    kappa = 2*p["rho"]/(r-mu)
    slope = p["gain"]/p["rho"]
    q = p["gain"]*mu/p["rho"].square() - p["maintenance"]/p["rho"]
    distance = a-b
    e = (-kappa*distance).exp()
    residual = slope*(b-p["eta"]*a) + (1-p["eta"])*q + slope/kappa*(1-p["eta"]*e) + cost
    f_mu = slope*((1-p["eta"])/p["rho"]
                  - (1-p["eta"]*e*(1+kappa*distance))/(kappa*r))
    derivative = (f_mu*p["drift_scale"]*(1-t.square())
                  + p["cost_drive"]*p["cost_span"]*(1-tc.square()))
    return residual, derivative


def invert_boundary(boundary, absolute, theta, reference_z, constants, deadline):
    """Certify exactly one root over the fixed domain; multiple roots abstain.

    At most 4096 cells and 80 bisections TOTAL per target, including all roots.
    Multiple roots exceeding this common budget abstain, never get extra work.
    """
    constants.validate()
    b, a, theta, anchor = map(exact, (boundary, absolute, theta, reference_z))
    if not ((Interval.point(a)-8).hi < b
            < (Interval.point(a)-Interval.point(Decimal("0.0001"))).lo):
        raise Abstain("BOUNDARY_OUTSIDE_ORIGINAL_QVI_BRACKET")
    ledger = Ledger(deadline)
    pending = [(Decimal(-8)+Decimal(i)/4, Decimal(-8)+Decimal(i+1)/4, 0)
               for i in reversed(range(64))]
    domain_complete = False
    active_cell = None
    try:
        while pending:
            ledger.check_time()
            if ledger.cells >= 4096:
                raise Abstain("ROOT_DOMAIN_CELL_BUDGET")
            lo, hi, depth = pending.pop()
            ledger.cells += 1
            cell = Interval(lo, hi)
            active_cell = cell
            f, derivative = residual_and_derivative(cell, b, a, theta, constants, ledger)
            if f.sign():
                ledger.discarded_cells += 1
                ledger.partition.append({"domain": [str(lo), str(hi)],
                                         "rule": "F_EXCLUDES_ZERO", "F": [str(f.lo), str(f.hi)]})
                active_cell = None
                continue
            if not derivative.sign():
                if depth >= 40:
                    raise Abstain("UNRESOLVED_NONMONOTONE_ROOT_CELL")
                mid = cell.midpoint()
                pending.append((mid, hi, depth+1))
                pending.append((lo, mid, depth+1))
                ledger.subdivisions += 1
                active_cell = None
                continue
            ledger.monotone_cells += 1
            flo, _ = residual_and_derivative(Interval.point(lo), b, a, theta, constants, ledger)
            fhi, _ = residual_and_derivative(Interval.point(hi), b, a, theta, constants, ledger)
            if not flo.sign() or not fhi.sign():
                raise Abstain("ENDPOINT_SIGN_UNCERTAIN")
            if flo.sign() == fhi.sign():
                ledger.discarded_cells += 1
                ledger.partition.append({"domain": [str(lo), str(hi)],
                                         "rule": "MONOTONE_SAME_ENDPOINT_SIGN",
                                         "Fz": [str(derivative.lo), str(derivative.hi)],
                                         "F_left": [str(flo.lo), str(flo.hi)],
                                         "F_right": [str(fhi.lo), str(fhi.hi)]})
                active_cell = None
                continue
            while cell.width() > Decimal("1e-12"):
                if ledger.bisections >= 80:
                    raise Abstain("ALL_ROOTS_BISECTION_BUDGET")
                ledger.bisections += 1
                mid = cell.midpoint()
                fm, _ = residual_and_derivative(Interval.point(mid), b, a, theta, constants, ledger)
                if not fm.sign():
                    raise Abstain("MIDPOINT_SIGN_UNCERTAIN")
                if fm.sign() == flo.sign():
                    lo, flo = mid, fm
                else:
                    hi, fhi = mid, fm
                cell = Interval(lo, hi)
            ledger.roots.append(cell)
            ledger.partition.append({"domain": [str(active_cell.lo), str(active_cell.hi)],
                                     "rule": "MONOTONE_UNIQUE_ROOT",
                                     "Fz": [str(derivative.lo), str(derivative.hi)],
                                     "root_interval": [str(cell.lo), str(cell.hi)],
                                     "F_left_root": [str(flo.lo), str(flo.hi)],
                                     "F_right_root": [str(fhi.lo), str(fhi.hi)]})
            active_cell = None
            if len(ledger.roots) > 1:
                raise Abstain("MULTIPLE_CERTIFIED_ROOTS")
        if active_cell is not None or 64+2*ledger.subdivisions != ledger.cells+len(pending):
            raise Abstain("PARTITION_ACCOUNTING_INCONSISTENT")
        domain_complete = True
        if not ledger.roots:
            raise Abstain("NO_CERTIFIED_ROOT_IN_FIXED_DOMAIN")
        chosen = ledger.roots[0]
        z_float = float(chosen.midpoint())
        if not chosen.lo <= Decimal.from_float(z_float) <= chosen.hi:
            raise Abstain("ROOT_ROUNDING_ESCAPES_BRACKET")
        final, _ = residual_and_derivative(Interval.point(z_float), b, a, theta, constants, ledger)
        if final.absolute().hi > Decimal("1e-10"):
            raise Abstain("REAL_SURROGATE_RESIDUAL_TOO_LARGE")
        return {"status": "ROOT_CERTIFIED_REAL_SURROGATE", "z": z_float,
                "selected_root": 0, "domain_complete": domain_complete, "residual": [str(final.lo), str(final.hi)],
                "all_roots": [[str(root.lo), str(root.hi)] for root in ledger.roots],
                "initial_cells": 64, "cells": ledger.cells, "subdivisions": ledger.subdivisions,
                "monotone_cells": ledger.monotone_cells, "discarded_cells": ledger.discarded_cells,
                "bisections": ledger.bisections, "partition_certificate": ledger.partition,
                "node_count_conservation": 64+2*ledger.subdivisions == ledger.cells+len(pending),
                "interval_evaluations": ledger.interval_evaluations,
                "point_evaluations": ledger.point_evaluations}
    except (Abstain, DecimalException) as original:
        error = original if isinstance(original, Abstain) else Abstain("DECIMAL_ARITHMETIC_REJECTED")
        error.evidence = {
            "domain_complete": domain_complete,
            "initial_cells": 64,
            "subdivisions": ledger.subdivisions,
            "monotone_cells": ledger.monotone_cells,
            "discarded_cells": ledger.discarded_cells,
            "unclassified_cells": len(pending)+int(active_cell is not None),
            "pending_domain_intervals": [[str(lo), str(hi), depth] for lo, hi, depth in pending],
            "active_unclassified_interval": (None if active_cell is None
                                             else [str(active_cell.lo), str(active_cell.hi)]),
            "node_count_conservation": 64+2*ledger.subdivisions == ledger.cells+len(pending),
            "partition_certificate": ledger.partition,
            "cells": ledger.cells,
            "bisections": ledger.bisections,
            "interval_evaluations": ledger.interval_evaluations,
            "point_evaluations": ledger.point_evaluations,
            "certified_roots_before_reject": [[str(root.lo), str(root.hi)] for root in ledger.roots],
        }
        if error is original:
            raise
        raise error from original
