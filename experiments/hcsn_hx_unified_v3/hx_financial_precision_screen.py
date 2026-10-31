"""True CPU dtype arithmetic + autograd for the *finite-maturity HX bond*.

All financial terms (including sigma, drift, discount and CDF) are computed in
Torch FP32/BF16; unlike parameter pre-quantization this evaluates the actual
low-precision arithmetic. F64 independent comparison is only a scientific
measurement. No native financial-equity/QVI gradient, interval theorem, or
GPU kernel is provided. Boundary-near inputs refuse.
"""
from dataclasses import dataclass
import math
import torch
from .hx_obstacle_grid_tail_v2 import bond_from_first_hit, UnresolvedObstacle


class UnresolvedFinancialPrecision(ValueError):
    pass


@dataclass(frozen=True)
class BondPrecisionRecord:
    dtype: str
    status: str
    asset: float
    boundary: float
    reference_bond: float
    low_precision_bond: float | None
    absolute_error: float | None
    relative_error: float | None
    asset_gradient: float | None
    reference_gradient: float | None
    normalized_gradient_error: float | None
    refusal: str | None


def _dtype(name):
    if name=='fp32': return torch.float32
    if name=='bf16': return torch.bfloat16
    if name=='fp64': return torch.float64
    raise UnresolvedFinancialPrecision('unsupported CPU dtype')


def _torch_bond(p,asset,b,t):
    asset_t=torch.tensor(asset,dtype=t,requires_grad=True)
    b_t=torch.tensor(b,dtype=t)
    values=[p.rate,p.payout,p.volatility,p.maturity,p.principal,
            p.coupon,p.recovery,p.shock_intensity,p.sale_fraction]
    r,d,s,T,P,C,R,lam,xi=torch.tensor(values,dtype=t).unbind()
    # A and boundary are already checked as strictly ordered by the caller.
    v=torch.log(asset_t/b_t)
    q=r+lam*xi
    a=(r-d-.5*s*s)/(s*s)
    z=torch.sqrt(a*a+2*q/(s*s))
    u=s*torch.sqrt(T)
    u2=u*u
    h1=(-v-a*u2)/u
    h2=(-v+a*u2)/u
    q1=(-v-z*u2)/u
    q2=(-v+z*u2)/u
    exponents=(-2*a*v,(-a+z)*v,(-a-z)*v)
    if any(not math.isfinite(float(x.detach())) or abs(float(x.detach()))>25
           for x in exponents):
        raise UnresolvedFinancialPrecision('CDF exponential outside screened range')
    F=torch.special.ndtr(h1)+torch.exp(exponents[0])*torch.special.ndtr(h2)
    G=torch.exp(exponents[1])*torch.special.ndtr(q1)+torch.exp(exponents[2])*torch.special.ndtr(q2)
    FF,GG=float(F.detach()),float(G.detach())
    if not (math.isfinite(FF) and math.isfinite(GG) and 0<=GG<=FF<=1):
        raise UnresolvedFinancialPrecision('quantized hit probability violates physical bounds')
    coupon=C/T
    par=P/T
    rec=R*b_t/T
    base=coupon/q
    price=base+torch.exp(-q*T)*(par-base)*(1-F)+(rec-base)*G
    if not math.isfinite(float(price.detach())):
        raise UnresolvedFinancialPrecision('nonfinite financial bond output')
    grad=torch.autograd.grad(price,asset_t)[0]
    if not math.isfinite(float(grad.detach())):
        raise UnresolvedFinancialPrecision('nonfinite financial bond derivative')
    return float(price.detach()),float(grad.detach())


def screen_financial_bond(p,asset:float,b:float,dtype:str)->BondPrecisionRecord:
    t=_dtype(dtype)
    try:
        if not (type(asset) in (int,float) and type(b) in (int,float)
                and math.isfinite(asset) and math.isfinite(b) and 0<b<asset):
            raise UnresolvedFinancialPrecision('invalid or at-boundary asset')
        from .hx_obstacle_grid_tail_v2 import _validate
        _validate(p,b,3.6,33)
        ref,_=bond_from_first_hit(p,asset,b)
        if not math.isfinite(ref):
            raise UnresolvedFinancialPrecision('independent reference not finite')
    except (ValueError,TypeError,OverflowError,UnresolvedObstacle) as e:
        raise UnresolvedFinancialPrecision('invalid physical reference') from e
    eps=torch.finfo(t).eps
    guard=8*eps*max(1.,abs(asset),abs(b))
    if asset-b<=guard:
        return BondPrecisionRecord(dtype,'REFUSE',asset,b,ref,None,None,None,
                                   None,None,None,'near-default quantization guard')
    try:
        price,grad=_torch_bond(p,asset,b,t)
        # Reference derivative via independent perturbed first-hit density,
        # not by autodiff of the candidate Torch CDF implementation.
        dh=max(4e-5,abs(asset)*5e-5)
        if asset-dh<=b:
            raise UnresolvedFinancialPrecision('derivative stencil crosses default')
        rp,_=bond_from_first_hit(p,asset+dh,b)
        rm,_=bond_from_first_hit(p,asset-dh,b)
        grad_ref=(rp-rm)/(2*dh)
        rel=abs(price-ref)/(1+abs(ref))
        gr_err=abs(grad-grad_ref)/(1+abs(grad_ref))
        if not all(math.isfinite(x) for x in (rel,grad,grad_ref,gr_err)):
            raise UnresolvedFinancialPrecision('nonfinite reference comparison')
    except (ValueError,ArithmeticError,RuntimeError,UnresolvedObstacle) as e:
        return BondPrecisionRecord(dtype,'REFUSE',asset,b,ref,None,None,None,
                                   None,None,None,f'{type(e).__name__}: {e}')
    return BondPrecisionRecord(dtype,'MEASURED_ONLY',asset,b,ref,price,
                               abs(price-ref),rel,grad,grad_ref,gr_err,None)
