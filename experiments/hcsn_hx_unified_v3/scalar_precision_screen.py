"""Empirical CPU FP32/BF16 screening of *scalar Brownian regenerative* threshold.

Unlike an input-only quantization test, comparison and implicit-residual
arithmetic actually run in PyTorch CPU FP32 or BF16. This does NOT certify
rounding, provide interval arithmetic, validate financial HX, cover GPU, or
measure active-set-gradient correctness. Treat near-boundary decisions as
REFUSE, never automatically accept from low precision.
"""
from dataclasses import dataclass
import math

import torch
from scipy.optimize import brentq


class UnresolvedPrecision(ValueError):
    pass


@dataclass(frozen=True)
class DecisionScreen:
    dtype: str
    boundary_f64: float
    boundary_quantized: float
    x: float
    low_precision_fire: bool
    reference_fire: bool
    status: str
    ambiguity_band: float


@dataclass(frozen=True)
class GradientScreen:
    dtype: str
    f64_gradients: tuple[float,...]
    quantized_gradients: tuple[float,...]
    normalized_max_error: float
    status: str


def _valid(p):
    try:
        vals=[p.drift,p.diffusion,p.discount,p.cost,p.reset,p.refractory]
    except AttributeError as exc:
        raise UnresolvedPrecision('missing scalar parameters') from exc
    if any(type(x) not in (float,int) or not math.isfinite(x) for x in vals):
        raise UnresolvedPrecision('nonfinite scalar physical parameters')
    if not (p.diffusion>0 and p.discount>0 and p.reset<p.cost and p.refractory>=0):
        raise UnresolvedPrecision('invalid scalar physical domain')


def _kappa(mu,sigma,rho):
    scale=math.hypot(mu,math.sqrt(2*rho)*sigma)
    return 2*rho/(scale+mu) if mu>=0 else (scale-mu)/(sigma*sigma)


def reference_threshold(p):
    """Independent f64 Brent smooth-fit root; no upstream Lambert-W import."""
    _valid(p)
    k=_kappa(p.drift,p.diffusion,p.discount)
    D=math.exp(-p.discount*p.refractory)
    def residual(b):
        return k*(b-p.cost)+D*math.exp(-k*(b-p.reset))-1
    lo=p.cost;hi=p.cost+1/k
    if not (math.isfinite(k) and k>0 and math.isfinite(hi) and
            residual(lo)<0 and residual(hi)>0):
        raise UnresolvedPrecision('unbracketed reference threshold')
    return brentq(residual,lo,hi,xtol=1e-13,rtol=1e-13)


def _dtype(dtype):
    if dtype=='fp32': return torch.float32
    if dtype=='bf16': return torch.bfloat16
    raise UnresolvedPrecision('unsupported precision')


def screen_action(p, x: float, dtype: str) -> DecisionScreen:
    """Conservative *empirical* ULP guard, not a proven rounding interval."""
    b=reference_threshold(p)
    t=_dtype(dtype)
    if type(x) not in (float,int) or not math.isfinite(x):
        raise UnresolvedPrecision('nonfinite scalar state')
    xq,bq=(float(v) for v in torch.tensor([x,b],dtype=t).tolist())
    low=xq>=bq
    high=x>=b
    # Eight nominal epsilons is only an engineering ambiguity screen;
    # it is deliberately NOT described as a rigorous bound for a full kernel.
    guard=8*torch.finfo(t).eps*max(1.,abs(x),abs(b))
    accepted=abs(x-b)>guard and low==high
    return DecisionScreen(dtype,b,bq,float(x),low,high,
                          'ACCEPT_SCREEN' if accepted else 'REFUSE',float(guard))


def _implicit_autograd(p,dtype):
    t=_dtype(dtype) if dtype!='fp64' else torch.float64
    b=reference_threshold(p)
    params=torch.tensor([p.drift,p.diffusion,p.discount,p.cost,p.reset,p.refractory],
                        dtype=t,requires_grad=True)
    bt=torch.tensor(b,dtype=t,requires_grad=True)
    mu,sigma,rho,K,r,tau=params.unbind()
    scale=torch.sqrt(mu*mu+2*rho*sigma*sigma)
    if p.drift>=0:
        k=2*rho/(scale+mu)
    else:
        k=(scale-mu)/(sigma*sigma)
    residual=k*(bt-K)+torch.exp(-rho*tau-k*(bt-r))-1
    gb,gt=torch.autograd.grad(residual,(bt,params))
    denom=float(gb.detach())
    if not math.isfinite(denom) or abs(denom)<1e-7:
        raise UnresolvedPrecision('singular quantized implicit derivative')
    out=(-gt/gb).detach().to(torch.float64).tolist()
    if any(not math.isfinite(v) for v in out):
        raise UnresolvedPrecision('nonfinite quantized implicit derivative')
    return tuple(float(v) for v in out)


def screen_implicit_gradient(p, dtype: str) -> GradientScreen:
    """Measure actual CPU dtype autograd error vs f64, never certify it."""
    _valid(p)
    ref=_implicit_autograd(p,'fp64')
    try:
        cand=_implicit_autograd(p,dtype)
    except UnresolvedPrecision:
        return GradientScreen(dtype,ref,(),math.inf,'REFUSE')
    error=max(abs(c-r)/(1+abs(r)) for c,r in zip(cand,ref))
    # This is a measurable diagnostic only, NOT admission for GPU/production.
    return GradientScreen(dtype,ref,cand,error,
                          'MEASURED_ONLY' if math.isfinite(error) else 'REFUSE')
