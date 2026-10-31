"""P1 research control: compare Call/Risk/Margin with signed-slope-matched gates.

A feature is supplied by the actual source under test; the calibrator does
NOT assert it is HX, optimal stopping, or a useful neural mechanism. The
anchor comes only from training data. Finite-difference slope is checked at
three noncommensurate resolutions with independent one-sided/central probes.
This is a local first-order comparison, not a matched information/cost/training
experiment. A reported affine fit never establishes new content benefit.
"""

from dataclasses import dataclass
import math
from typing import Callable


class UnresolvedAnchor(ValueError):
    """Refuse degenerate, nonsmooth or ill-conditioned local comparisons."""


@dataclass(frozen=True)
class MatchedAnchor:
    channel: str
    anchor: float
    original_value: float
    signed_input_slope: float
    gain: float
    intercept: float
    matched_target_value: float
    matched_target_slope: float
    max_slope_discrepancy: float
    is_global_equivalence: bool = False

    def evaluate(self, source_value: float) -> float:
        if type(source_value) not in (float,int) or not math.isfinite(source_value):
            raise UnresolvedAnchor('nonfinite channel value')
        v=math.fsum((self.intercept,self.gain*source_value))
        if not math.isfinite(v):
            raise UnresolvedAnchor('unresolved affine output')
        return v


def match_value_and_signed_slope(channel: str, fn: Callable[[float],float],
                                 anchor: float, *, target_value: float,
                                 target_slope: float, relative_step: float=1e-4,
                                 max_gain: float=1e4,
                                 slope_tolerance: float=1e-3) -> MatchedAnchor:
    """Return an explicit local affine calibration, or fail closed.

    For features with non-smooth kinks or nearly zero slope no derivative is
    invented. The multi-step probe is only an empirical local diagnostic;
    adversarial functions can still alias every finite stencil.
    """
    if channel not in ('call','risk','margin') or not callable(fn):
        raise UnresolvedAnchor('unknown feature channel or function')
    vals=(anchor,target_value,target_slope,relative_step,max_gain,slope_tolerance)
    if (any(type(x) not in (int,float) or not math.isfinite(x) for x in vals) or
            anchor<=0 or relative_step<=0 or max_gain<=0 or
            not 0<slope_tolerance<.1 or abs(target_slope)<1e-8):
        raise UnresolvedAnchor('invalid or degenerate signed-slope contract')
    h=relative_step*max(1.,abs(anchor))
    scales=(1.,1./3,1/math.sqrt(7.))
    if h>=anchor/2 or anchor+h==anchor or any(anchor-h*s<=0 for s in scales):
        raise UnresolvedAnchor('nonpositive or unresolvable sampling neighborhood')
    def observe(x):
        try:
            v=fn(float(x))
        except (ValueError,OverflowError,ArithmeticError,ZeroDivisionError) as ex:
            raise UnresolvedAnchor('feature undefined at anchor neighborhood') from ex
        if type(v) not in (float,int) or not math.isfinite(v):
            raise UnresolvedAnchor('nonfinite feature evaluation')
        return float(v)
    y=observe(anchor)
    slopes=[]
    for scale in scales:
        d=h*scale
        plus,minus=observe(anchor+d),observe(anchor-d)
        right=(plus-y)/d
        left=(y-minus)/d
        center=(plus-minus)/(2*d)
        if not all(math.isfinite(z) for z in (right,left,center)):
            raise UnresolvedAnchor('nonfinite finite differences')
        # Compare one-sided slopes at the smallest stencil. At smooth points
        # their difference is O(h) while at kinks it stays O(1).
        slopes.append((left,right,center))
    base=slopes[-1][2]
    if abs(base)<1e-8 or not math.isfinite(base):
        raise UnresolvedAnchor('zero or unresolved source slope')
    discrepancy=max(abs(s-base) for _,_,s in slopes)
    discrepancy=max(discrepancy,abs(slopes[-1][0]-slopes[-1][1]))
    if discrepancy>slope_tolerance*max(abs(base),1e-4):
        raise UnresolvedAnchor('inconsistent input slope or active-set kink')
    gain=target_slope/base
    intercept=math.fsum((target_value,-gain*y))
    if (not all(math.isfinite(z) for z in (gain,intercept)) or
            abs(gain)>max_gain or
            abs(math.fsum((intercept,gain*y))-target_value)>1e-11*max(1.,abs(target_value)) or
            abs(gain*base-target_slope)>1e-11*max(1.,abs(target_slope))):
        raise UnresolvedAnchor('nonfinite or ill-conditioned local affine match')
    return MatchedAnchor(channel,float(anchor),y,base,gain,intercept,
                         target_value,target_slope,discrepancy)
