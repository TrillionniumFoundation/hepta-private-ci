"""Affine moving free-boundary first-passage operators for an HCSN research cell.

Mathematical scope: X(t) = log(V(t)/B(t)) = x0 + (drift - slope)*t + sigma*W(t),
where log B(t)=log B(0)+slope*t; x0 >= 0. For tau=inf{t>=0:X(t)<=0},
this module returns F(T)=Pr(tau<=T) and G(T)=E[exp(-discount*tau) 1(tau<=T)].
They are **exact only for an affine log boundary and constant coefficients**.
No assumption of the original He--Xiong equity/pricing/QVI model is made.

The finite-horizon closed forms derive from the absorbing Brownian reflection
principle. They are differentiable at positive x,T,sigma,discount inside the
admissible domain; not across the initial-contact and zero-horizon branches.
Neither output is a true sampled binary spike, nor a validation of neural utility.

A separate first-hitting-time density integral is provided as an independent
numerical reference. It does not evaluate the CDF formula or call this module's
closed form. Its integral is transformed to u=x/(sigma*sqrt(t)) to handle the
near-contact t=0 density singularity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad
import torch


@dataclass(frozen=True)
class AffineHitting:
    probability: torch.Tensor
    discounted_probability: torch.Tensor


def affine_hitting_torch(
    x0: torch.Tensor,
    horizon: torch.Tensor,
    drift: torch.Tensor,
    sigma: torch.Tensor,
    boundary_slope: torch.Tensor,
    discount: torch.Tensor,
) -> AffineHitting:
    """Batch-broadcastable FP64 first hitting (F,G) with torch.autograd.

    All tensors must be floating-point FP64 on the same device, and all inputs
    must have shapes broadcastable to a common output; no silent truncation or
    changing the result via lower-precision intermediate arithmetic.
    x0=0 causes immediate hitting even at T=0; x0>0,T=0 causes no hitting.
    Gradients are certified by tests for x0,T,sigma,discount>0, away from
    branch transitions. Discount=0 uses G=F exactly; do not assume a correct
    derivative of G with respect to discount at that branch.
    """
    inputs=(x0,horizon,drift,sigma,boundary_slope,discount)
    if any(not isinstance(v,torch.Tensor) or v.dtype!=torch.float64 for v in inputs):
        raise TypeError('All inputs must be FP64 torch tensors; explicitly cast quantized inputs')
    if any(v.device != x0.device for v in inputs):
        raise ValueError('Inputs must be on same device')
    try:
        x,T,nu,sig,sl,lam=torch.broadcast_tensors(*inputs)
    except RuntimeError as exc:
        raise ValueError('Incompatible batch shapes') from exc
    # Explicit, documented numerical support domain. Outside it we fail
    # closed rather than return NaN for an otherwise-finite extreme input.
    if (x.numel()>2_000_000
        or any(not bool(torch.isfinite(v).all()) for v in (x,T,nu,sig,sl,lam))
        or bool((x<0).any()) or bool((x>100).any())
        or bool((T<0).any()) or bool((T>1.e4).any())
        or bool((sig<1.e-5).any()) or bool((sig>5).any())
        or bool((nu.abs()>20).any()) or bool((sl.abs()>20).any())
        or bool((lam<0).any()) or bool((lam>20).any())):
        raise ValueError('Outside bounded FP64 numerical reference domain')

    # Prevent invalid 0 divisions in untaken torch.where branches.
    safe_T=torch.where(T>0,T,torch.ones_like(T))
    safe_x=torch.where(x>0,x,torch.ones_like(x))
    mu=nu-sl
    # Compute the safe radicand BEFORE sqrt. Clamping z after sqrt(0)
    # propagates 0 * infinity -> NaN through the *unselected* autograd branch.
    # At discount=0, G is explicitly F and its discount derivative is not
    # certified; at mu=0 too, the unused sqrt must not poison dF/dmu.
    radicand=mu*mu+2*lam*sig*sig
    z=torch.sqrt(torch.where((lam==0)&(mu==0),torch.ones_like(radicand),radicand))
    st=sig*torch.sqrt(safe_T)
    a=(-safe_x-mu*safe_T)/st
    b=(-safe_x+mu*safe_T)/st
    log_f=torch.logaddexp(torch.special.log_ndtr(a),
                          -2*mu*safe_x/(sig*sig)+torch.special.log_ndtr(b))
    f=torch.exp(log_f)
    za=(-safe_x-z*safe_T)/st
    zb=(-safe_x+z*safe_T)/st
    log_g=torch.logaddexp((z-mu)*safe_x/(sig*sig)+torch.special.log_ndtr(za),
                          (-z-mu)*safe_x/(sig*sig)+torch.special.log_ndtr(zb))
    g=torch.where(lam==0, f, torch.exp(log_g))
    f=torch.where(x==0,torch.ones_like(f),torch.where(T==0,torch.zeros_like(f),f))
    g=torch.where(x==0,torch.ones_like(g),torch.where(T==0,torch.zeros_like(g),g))
    # No unconditional clamping: it hides invalid models and changes gradients.
    # Physically F,G belong to [0,1] and G<=F; tolerate only FP64 roundoff.
    if (not bool(torch.isfinite(f).all()) or not bool(torch.isfinite(g).all())
        or bool(((f < -5e-13)|(f > 1+5e-13)|(g < -5e-13)|(g > f+5e-13)).any())):
        raise ArithmeticError('Nonfinite or physically invalid first-passage probability')
    return AffineHitting(f,g)


def density_reference(x0:float, horizon:float, drift:float, sigma:float,
                      boundary_slope:float, discount:float) -> tuple[float,float]:
    """Independent integration of inverse-Gaussian first hitting density.

    Computes F and G by two separate numerical integrals. This never calls
    ``affine_hitting_torch`` nor evaluates a normal-CDF closed-form expression.
    With x>0, substitution u=x/(sigma*sqrt(t)) regularizes the t=0 singularity.
    Negative and positive relative drifts are both supported.
    """
    vals=(x0,horizon,drift,sigma,boundary_slope,discount)
    if (not all(math.isfinite(v) for v in vals) or x0<0 or horizon<0
            or sigma<=0 or discount<0):
        raise ValueError('Invalid independent density reference inputs')
    if x0==0:
        return 1.,1.
    if horizon==0:
        return 0.,0.
    mu=drift-boundary_slope
    umin=x0/(sigma*math.sqrt(horizon))
    a=mu*x0/sigma**2
    tscale=(x0/sigma)**2
    # exponent=-(u+a/u)^2/2 - discount*tscale/u^2
    def dens(u, lam):
        if u==0:
            return 0.
        term=u+a/u
        expo=-.5*term*term-lam*tscale/(u*u)
        return math.sqrt(2/math.pi)*math.exp(expo) if expo>-745 else 0.
    f=quad(lambda u:dens(u,0.),umin,np.inf,epsabs=2e-12,epsrel=2e-11,limit=250)[0]
    g=quad(lambda u:dens(u,discount),umin,np.inf,epsabs=2e-12,epsrel=2e-11,limit=250)[0]
    return f,g


def sample_affine_hitting(x0:float, drift:float, sigma:float,
                          boundary_slope:float, n:int, seed:int=7) -> np.ndarray:
    """Independent *exact-time* first-hit Monte Carlo for affine log boundary.

    Generates possibly infinite hitting times using the inverse-Gaussian law.
    This does not discretize Brownian paths and so has no timestep crossing bias.
    Use only for x0>0, finite constant coefficients, and n in [1, 3 million].
    """
    if (not all(map(math.isfinite,(x0,drift,sigma,boundary_slope)))
            or x0<=0 or sigma<=0 or not 1<=n<=3000000):
        raise ValueError('Invalid first-hit sampling parameters')
    mu=drift-boundary_slope
    rng=np.random.default_rng(seed)
    if abs(mu)<1e-14:
        z=rng.standard_normal(n)
        return (x0/(sigma*z))**2
    mean=x0/abs(mu)
    shape=(x0/sigma)**2
    # A Brownian motion moving away from the barrier has a defective law.
    # Conditional on ever hitting, its first-hit time is IG(x/|mu|,x^2/sigma^2).
    samples=rng.wald(mean,shape,size=n)
    if mu>0:
        eventual_probability=math.exp(-2*mu*x0/sigma**2)
        samples[rng.random(n)>eventual_probability]=np.inf
    return samples


@dataclass(frozen=True)
class PiecewiseHittingEstimate:
    hit_probability: float
    standard_error: float
    paths: int
    segments: int
    method: str = 'exact-conditional-Brownian-bridge-Monte-Carlo'


def piecewise_affine_hitting_mc(x0:float, drift:float, sigma:float,
                                boundary_slopes:np.ndarray, durations:np.ndarray,
                                *, paths:int=100000, seed:int=7) -> PiecewiseHittingEstimate:
    """Unbiased Monte Carlo hit probability for a PIECEWISE-linear log boundary.

    This estimates hit-by-final-time, not a discounted hitting value or an
    analytical solution of the full time-dependent QVI. On each segment, the
    conditional Brownian-bridge no-crossing probability, given positive
    endpoints x,y, equals 1-exp(-2*x*y/(sigma^2*dt)); thus observing only
    segment endpoints does not incur a grid-crossing bias. No exact event times
    are produced. For piecewise drifts/volatilities this method requires an
    extension; this reference fixes constant drift and volatility throughout.
    """
    s=np.asarray(boundary_slopes,dtype=np.float64)
    t=np.asarray(durations,dtype=np.float64)
    if (not all(map(math.isfinite,(x0,drift,sigma))) or x0<0 or sigma<=0
            or not 100<=paths<=1000000 or s.ndim!=1 or t.ndim!=1
            or s.shape!=t.shape or not 1<=len(t)<=128
            or not np.isfinite(s).all() or not np.isfinite(t).all()
            or not (t>0).all()):
        raise ValueError('Invalid piecewise log-boundary inputs')
    if x0==0:
        return PiecewiseHittingEstimate(1.,0.,paths,len(t))
    rng=np.random.default_rng(seed)
    x=np.full(paths,x0,dtype=np.float64)
    alive=np.ones(paths,dtype=bool)
    for slope,dt in zip(s,t):
        idx=np.flatnonzero(alive)
        if len(idx)==0:
            break
        y=x[idx]+(drift-slope)*dt+sigma*math.sqrt(dt)*rng.standard_normal(len(idx))
        keep=y>0
        if keep.any():
            prob=-np.expm1(-2*x[idx[keep]]*y[keep]/(sigma*sigma*dt))
            keep_indices=np.flatnonzero(keep)
            keep[keep_indices]=rng.random(len(keep_indices))<prob
        alive[idx]=keep
        x[idx]=y
    hit=1.-float(alive.mean())
    se=math.sqrt(hit*(1-hit)/paths)
    return PiecewiseHittingEstimate(hit,se,paths,len(t))
