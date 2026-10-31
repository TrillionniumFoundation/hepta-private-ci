"""P1 local-slope-matched mechanism controls; research-only, not a winner gate.

A frozen affine output reparameterization alpha + beta * channel(z) matches
an ordinary gate in both value and d/dz at one *training-only* anchor.
This does not match curvature, dynamic memory, FLOPs, trainable parameters,
or end-to-end utility. Matching must precede access to held-out labels.
"""

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class SlopeMatch:
    anchor: float
    offset: float
    scale: float
    channel_value: float
    channel_slope: float
    ordinary_value: float
    ordinary_slope: float
    stencil_rel_disagreement: float
    step: float

    def calibrated(self, channel_value: float) -> float:
        value = self.offset + self.scale * channel_value
        if not math.isfinite(value):
            raise ArithmeticError('Matched output outside finite f64 domain')
        return value


def _profile(f: Callable[[float], float], anchor: float, step: float):
    """Five-point/one-sided derivatives on three noncommensurate scales.

    Coarse and half-step probes alone share sampling-grid aliases: a
    high-frequency perturbation can vanish at both sets of stencil points,
    falsely matching a gate whose true local slope differs by orders of
    magnitude. Add a sqrt(1/2) scale as an independent alias diagnostic.
    Finite stencils can still be fooled; this is NOT derivative certification.
    """
    if anchor - 2 * step == anchor or anchor + 2 * step == anchor:
        raise ArithmeticError('Stencil offsets erased in f64')
    samples = {}
    for ratio in (1., .5, math.sqrt(.5)):
        h = step * ratio
        if h <= 0 or anchor - 2*h == anchor or anchor + 2*h == anchor:
            raise ArithmeticError('Unrepresentable derivative step')
        ys = []
        for multiple in (-2, -1, 0, 1, 2):
            z = anchor + multiple*h
            if not math.isfinite(z):
                raise ArithmeticError('Nonfinite stencil argument')
            try:
                y = float(f(z))
            except (OverflowError, ZeroDivisionError, ValueError) as exc:
                raise ValueError('Channel not admissible throughout stencil') from exc
            if not math.isfinite(y):
                raise ArithmeticError('Nonfinite stencil value')
            ys.append(y)
        derivative = (ys[0]-8*ys[1]+8*ys[3]-ys[4])/(12*h)
        left = (3*ys[2]-4*ys[1]+ys[0])/(2*h)
        right = (-3*ys[2]+4*ys[3]-ys[4])/(2*h)
        if not all(map(math.isfinite, (derivative,left,right))):
            raise ArithmeticError('Nonfinite local derivative')
        samples[ratio] = (ys[2], derivative, left, right)
    finer = samples[.5]
    if any(entry[0]!=finer[0] for entry in samples.values()):
        raise ArithmeticError('Non-deterministic channel at anchor')
    disagreement=max(
        max(abs(entry[1]-finer[1]),abs(entry[2]-entry[3]))
        for entry in samples.values()
    )
    return finer[0], finer[1], disagreement

def match_local_slope(
    channel: Callable[[float], float],
    ordinary: Callable[[float], float],
    *,
    anchor: float,
    step: float = 0.001,
    slope_floor: float = 1e-7,
    relative_tolerance: float = 0.005,
    maximum_abs_scale: float = 1e6,
) -> SlopeMatch:
    """Fail closed unless value and signed local derivative can be matched.

    Both curves must be finite and smooth within the complete +/-2*step
    window, with stable derivatives at steps h and h/2. This is a local
    *numerical* agreement check, not an interval proof or causal experiment.
    """
    args=(anchor,step,slope_floor,relative_tolerance,maximum_abs_scale)
    if (not all(map(math.isfinite,args)) or step<=0 or slope_floor<=0
            or not 0<relative_tolerance<1 or maximum_abs_scale<=0):
        raise ValueError('Invalid local matching numerical contract')
    c,dc,ec = _profile(channel,anchor,step)
    o,do,eo = _profile(ordinary,anchor,step)
    if min(abs(dc),abs(do)) < slope_floor:
        raise ArithmeticError('Near-zero channel/ordinary derivative')
    relative=max(ec/abs(dc),eo/abs(do))
    if relative > relative_tolerance:
        raise ArithmeticError('Local derivative unstable or nonsmooth')
    beta=do/dc
    alpha=math.fsum((o,-beta*c))
    if not (math.isfinite(alpha) and math.isfinite(beta)
            and abs(beta)<=maximum_abs_scale):
        raise ArithmeticError('Matched affine gain not representable or too large')
    return SlopeMatch(anchor=anchor,offset=alpha,scale=beta,
                      channel_value=c,channel_slope=dc,
                      ordinary_value=o,ordinary_slope=do,
                      stencil_rel_disagreement=relative,step=step)


def ordinary_sigmoid(z: float) -> float:
    """Stable, explicitly ordinary (non-HX) trainable-gate shape."""
    if z >= 0:
        e=math.exp(-z)
        return 1/(1+e)
    e=math.exp(z)
    return e/(1+e)


def hx_log_asset_curve(p, channel_name: str, *, asset_boundary: float | None = None,
                       boundary_exclusion: float = 0.001):
    """Strict financial feature adapter with z = log(V/V_B), no neural claim.

    Call is the financial E(V), Risk is F(T), Survival is 1-F(T), and
    Margin is d(V,T)-p/T. F/G physical probability ordering and financial
    E(V)>=0 are necessary for admission. They are NOT a sufficient global
    obstacle/fixed-point certificate. Never clip a bad region to make a gate.
    """
    from .hx import boundary, mechanism_channels

    allowed={'call':'equity','risk':'default_probability',
             'survival':'default_probability','margin':'rollover_margin'}
    if channel_name not in allowed:
        raise ValueError('Unknown financial mechanism channel')
    if not math.isfinite(boundary_exclusion) or boundary_exclusion<=0:
        raise ValueError('Boundary exclusion must be positive')
    b=boundary(p) if asset_boundary is None else asset_boundary
    if not (math.isfinite(b) and b>0):
        raise ValueError('Invalid financial boundary')

    def curve(z: float) -> float:
        if not math.isfinite(z) or z<=boundary_exclusion:
            raise ValueError('Near-boundary, default, or nonfinite log-asset state')
        try:
            asset=b*math.exp(z)
        except OverflowError as exc:
            raise ArithmeticError('Asset exp outside representable f64 domain') from exc
        if not math.isfinite(asset) or asset<=b:
            raise ArithmeticError('Financial asset mapping not representable')
        c=mechanism_channels(p,asset,b)
        values=(c.equity,c.default_probability,c.discounted_default_factor,
                c.rollover_margin)
        if not all(map(math.isfinite,values)):
            raise ArithmeticError('Nonfinite financial mechanism channels')
        if (c.equity<0 or not 0<=c.discounted_default_factor
                <=c.default_probability<=1):
            raise ValueError('Necessary HX nonnegative-obstacle/probability gate fails')
        value=getattr(c,allowed[channel_name])
        return 1-value if channel_name=='survival' else value
    return curve
