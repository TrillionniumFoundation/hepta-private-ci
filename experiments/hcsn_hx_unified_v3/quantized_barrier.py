"""Fail-closed float32 barrier-ordering guard for the independent HCSN oracle.

This reasons about all positive real numbers rounding to two supplied fp32
encodings (IEEE-754 nearest-even). It does not recover sub-ulp information,
certify floating-point quadrature, or provide a fp32 native compute kernel.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .bond_fpt_independent import integrate_passage


@dataclass(frozen=True)
class RoundingCell:
    encoded: float
    lower: float
    upper: float


@dataclass(frozen=True)
class BarrierOrdering:
    status: str
    asset: RoundingCell
    boundary: RoundingCell


@dataclass(frozen=True)
class ProbabilityBracket:
    lower_f: float
    upper_f: float
    lower_g: float
    upper_g: float
    # SciPy quad error estimates, NOT rigorous interval bounds.
    estimated_numerical_error: float


def fp32_cell(value: float) -> RoundingCell:
    """Conservatively enclose positive reals rounding to the same fp32 value.

    Midpoints between neighboring fp32 numbers define the nearest-even
    rounding cell; outward f64 nextafter covers ties and midpoint rounding.
    Reject overflow/underflow/nonpositive encoding instead of guessing.
    """
    if not math.isfinite(value) or value <= 0:
        raise ValueError('The original state must be positive and finite')
    with np.errstate(over='ignore', under='ignore', invalid='ignore'):
        encoded = np.float32(value)
    if not np.isfinite(encoded) or encoded <= 0:
        raise ValueError('Float32 state encoding overflowed or underflowed')
    predecessor = np.nextafter(encoded, np.float32(-math.inf))
    successor = np.nextafter(encoded, np.float32(math.inf))
    if not np.isfinite(successor) or predecessor < 0:
        raise ValueError('Float32 rounding-cell endpoint is not finite')
    q, p, n = float(encoded), float(predecessor), float(successor)
    lo = math.nextafter((q+p)*.5, -math.inf)
    hi = math.nextafter((q+n)*.5, math.inf)
    if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= q <= hi):
        raise ArithmeticError('Invalid float32 rounding cell')
    return RoundingCell(q, lo, hi)


def classify_fp32_barrier(asset: float, boundary: float) -> BarrierOrdering:
    """ABOVE/BELOW only when *all* consistent fp32 preimages agree."""
    a = fp32_cell(asset)
    b = fp32_cell(boundary)
    if a.lower > b.upper:
        status = 'ABOVE'
    elif a.upper < b.lower:
        status = 'BELOW'
    else:
        status = 'AMBIGUOUS'
    return BarrierOrdering(status, a, b)


def guarded_fp32_passage(asset: float, boundary: float, *,
                         drift: float, sigma: float, discount: float,
                         horizon: float) -> tuple[BarrierOrdering, ProbabilityBracket | None]:
    """Diagnostic F/G range from rounding-cell extremal log distances.

    The ordering is conservative under the stated round-to-nearest model;
    the computed F/G range is only numerical, because scipy quad error
    estimates do not prove validated real-number interval enclosures.
    """
    ordering = classify_fp32_barrier(asset, boundary)
    if not all(math.isfinite(v) for v in (drift,sigma,discount,horizon)) or not (
            sigma > 0 and discount > 0 and horizon > 0):
        raise ValueError('Invalid Brownian first-passage parameters')
    if ordering.status == 'AMBIGUOUS':
        return ordering, None
    if ordering.status == 'BELOW':
        # Already on the stopped side for every real represented value.
        return ordering, ProbabilityBracket(1.,1.,1.,1.,0.)
    a, b = ordering.asset, ordering.boundary
    nearest_x = math.log(a.lower)-math.log(b.upper)
    farthest_x = math.log(a.upper)-math.log(b.lower)
    if not (0 < nearest_x <= farthest_x):
        # Do not trust subtraction of logarithms in a degenerate f64 region.
        return BarrierOrdering('AMBIGUOUS',a,b), None
    near = integrate_passage(nearest_x,drift=drift,sigma=sigma,
                             discount=discount,horizon=horizon)
    far = integrate_passage(farthest_x,drift=drift,sigma=sigma,
                            discount=discount,horizon=horizon)
    estimated_error = (near.absolute_error_bound+far.absolute_error_bound)
    if (far.probability > near.probability + 4*estimated_error or
            far.discounted > near.discounted + 4*estimated_error):
        raise ArithmeticError('First-passage monotonicity violated')
    def bounds(x, y):
        return max(0.,min(x,y)-estimated_error),min(1.,max(x,y)+estimated_error)
    flo,fhi=bounds(far.probability,near.probability)
    glo,ghi=bounds(far.discounted,near.discounted)
    return ordering,ProbabilityBracket(flo,fhi,glo,ghi,estimated_error)
