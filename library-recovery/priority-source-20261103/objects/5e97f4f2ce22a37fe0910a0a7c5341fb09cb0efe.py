"""P1 controlled comparison: genuine Call/Risk/Margin value and slope matching.

This local audit removes a first-order confound in the HCSN vs ordinary-gate
comparison: gates can have entirely different input derivatives at an anchor.
It uses the standard perpetual GBM Put (not the full HX equilibrium) for the
illustrative Call-like feature, drifted Brownian first hit for Risk, and
log(V/b) for Margin. All values and derivatives are defined in physical V.

Given *training-only* anchor V0, target ordinary-gate value y0 and signed
slope dy/dV, produce an affine calibration y=alpha+beta*feature(V) such that
both value and signed derivative coincide at V0. This is an algebraic
reference, NOT a demonstration of feature benefit, matched information,
matched compute, completed ablation, or foundation-scale capability.

Zero-slope, nonsmooth/absorbed, unstable-scale, and outside-domain anchors are
explicit refusals. Near-boundary f32 aliasing and low-precision kernels are
separately gated; no automatic clipping or subgradient is silently supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from scipy.special import ndtr

from .perpetual_put_qvi_reference import GBMPut


class UnresolvedCalibration(ValueError):
    pass


@dataclass(frozen=True)
class FeatureDerivative:
    channel: str
    value: float
    signed_dv: float
    state: float
    boundary: float


@dataclass(frozen=True)
class AffineGate:
    channel: str
    intercept: float
    gain: float
    train_anchor: float
    target_value: float
    target_signed_dv: float

    def forward(self, feature_value: float) -> float:
        if type(feature_value) not in (float,int) or not math.isfinite(feature_value):
            raise UnresolvedCalibration('nonfinite feature')
        out=math.fsum((self.intercept,self.gain*feature_value))
        if not math.isfinite(out):
            raise UnresolvedCalibration('affine projection nonfinite')
        return out


def channel_at(p: GBMPut, v: float, channel: str, *, horizon: float=.5,
               drift: float=.02, diffusion: float=.25) -> FeatureDerivative:
    if (type(v) not in (float,int) or not math.isfinite(v) or v<=0 or
            channel not in ('call','risk','margin')):
        raise UnresolvedCalibration('positive finite physical state and known channel required')
    b=p.boundary
    if not math.isfinite(b) or b<=0:
        raise UnresolvedCalibration('reference boundary unresolved')
    if channel=='call':
        # Call-like residual: V-K+perpetual_put(V), not literal HX equity.
        if v<=b:
            value=slope=0.
        else:
            put=p.value(v)
            value=math.fsum((v,-p.strike,put))
            slope=1+p.beta_minus*put/v
    elif channel=='margin':
        value=math.log(v/b)
        slope=1/v
    else:
        if not all(type(t) in (float,int) and math.isfinite(t)
                   for t in (horizon,drift,diffusion)) or horizon<=0 or diffusion<=0:
            raise UnresolvedCalibration('finite T>0, sigma>0 and drift required')
        x=math.log(v/b)
        if x<=0:
            value=1.
            slope=0.
        else:
            s=diffusion*math.sqrt(horizon)
            z1=(-x-drift*horizon)/s
            z2=(-x+drift*horizon)/s
            exponent=-2*drift*x/(diffusion*diffusion)
            if not math.isfinite(exponent) or exponent>700 or x>100:
                raise UnresolvedCalibration('first-hit derivative scale unresolved')
            e=math.exp(exponent)
            phi1=math.exp(-z1*z1/2)/math.sqrt(2*math.pi)
            phi2=math.exp(-z2*z2/2)/math.sqrt(2*math.pi)
            value=float(ndtr(z1)+e*ndtr(z2))
            slope=(-phi1/s+e*((-2*drift/(diffusion*diffusion))*ndtr(z2)
                                  -phi2/s))/v
            if not 0<value<1:
                raise UnresolvedCalibration('first-hit output rounded to degenerate probability')
    if not math.isfinite(value) or not math.isfinite(slope):
        raise UnresolvedCalibration('feature value or slope unresolved')
    return FeatureDerivative(channel,float(value),float(slope),float(v),float(b))


def affine_match(feature: FeatureDerivative, *, target_value: float,
                 target_signed_dv: float, min_abs_derivative: float=1e-8,
                 max_gain: float=1e4) -> AffineGate:
    """Local value AND signed physical-state derivative match.

    This should be performed only using frozen training anchors. Signed
    derivative is matched exactly, not its magnitude. Beta may be negative;
    to test the financial mechanism rather than input slope alone, controls
    must also get the same information/parameter/cost budget elsewhere.
    """
    if not isinstance(feature,FeatureDerivative):
        raise UnresolvedCalibration('complete analytic feature required')
    vals=(feature.value,feature.signed_dv,feature.state,feature.boundary,
          target_value,target_signed_dv,min_abs_derivative,max_gain)
    if not all(type(t) in (int,float) and math.isfinite(t) for t in vals):
        raise UnresolvedCalibration('nonfinite calibration input')
    if (feature.state<=0 or feature.boundary<=0 or
            min_abs_derivative<=0 or max_gain<=0 or
            abs(feature.signed_dv)<min_abs_derivative or
            abs(target_signed_dv)<min_abs_derivative or
            abs(feature.state-feature.boundary)
              <=1e-8*max(1.,feature.boundary)):
        raise UnresolvedCalibration('near boundary, flat or unresolvable local derivative')
    gain=target_signed_dv/feature.signed_dv
    intercept=math.fsum((target_value,-gain*feature.value))
    if (not math.isfinite(gain) or not math.isfinite(intercept)
            or abs(gain)>max_gain):
        raise UnresolvedCalibration('calibration gain beyond admissible budget')
    if abs(math.fsum((intercept,gain*feature.value))-target_value)>1e-10*max(1.,abs(target_value)):
        raise UnresolvedCalibration('calibrated local value unresolved in f64')
    if abs(gain*feature.signed_dv-target_signed_dv)>1e-10*max(1.,abs(target_signed_dv)):
        raise UnresolvedCalibration('calibrated signed gradient unresolved in f64')
    return AffineGate(feature.channel,intercept,gain,feature.state,target_value,target_signed_dv)
