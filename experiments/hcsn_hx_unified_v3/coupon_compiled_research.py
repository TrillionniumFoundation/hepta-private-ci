"""Explicit compiled-callback research path; original HX APIs remain unchanged.

The adaptive algorithm, partitions and tolerances match the Python helper.
A sticky callback error discards each quad result before any accumulation.
"""
import math
import ctypes
from scipy import LowLevelCallable
from . import _coupon_kernel
from .hx import HX,_first_passage_factors,_log_asset_ratio

def coupon_annuity_compiled(p: HX, x: float, tau: float) -> float:
    """Integrate E[int_0^min(hit,tau) exp(-q*t) dt] directly.

    Uses reflected survival probabilities, not a difference of discounted
    passage probabilities. Adaptive error estimates are diagnostic, not
    rigorous enclosures. This slow research path has no production claim.
    """
    from scipy.integrate import IntegrationWarning, quad

    sigma=p.volatility
    drift=p.rate-p.payout-.5*sigma*sigma
    q=p.q
    if not all(math.isfinite(z) for z in (x,drift,q)) or q <= 0:
        raise ArithmeticError('HX coupon transformed parameters unresolved')
    upper=math.sqrt(tau)
    transition=x/sigma
    if not math.isfinite(transition) or transition <= 0:
        raise ArithmeticError('HX coupon time scale unresolved')
    context=_coupon_kernel.Context(x,sigma,drift,q)
    integrand=LowLevelCallable.from_cython(_coupon_kernel,'survival',ctypes.c_void_p(context.address()))
    # Resolve both first-passage and discount boundary layers. Whole-interval
    # adaptive quadrature can otherwise miss a narrow positive contribution
    # and misleadingly report zero estimated error.
    scales=[transition,1/math.sqrt(q)]
    if drift:
        drift_scale=math.sqrt(x)/math.sqrt(abs(drift))
        if not math.isfinite(drift_scale) or drift_scale <= 0:
            raise ArithmeticError('HX coupon drift time scale unresolved')
        scales.append(drift_scale)
    cuts=sorted({0.,upper,*[z for scale in scales for z in (scale,4*scale,8*scale)
                          if 0<z<upper]})
    total=error=0.
    # full_output transports QUADPACK failure messages as return values;
    # do not mutate process-global warning filters in concurrent callers.
    try:
        for lo,hi in zip(cuts,cuts[1:]):
            result=quad(integrand,lo,hi,epsabs=1e-11*min(tau,1.),
                        epsrel=2e-10,limit=200,full_output=1)
            if context.error():
                raise ArithmeticError('HX compiled coupon callback unresolved: '+str(context.error()))
            # Success is (value, error, info). Non-convergence appends a
            # message (and some weighted modes append another explanation).
            if len(result)!=3:
                raise ArithmeticError('HX coupon survival integration unresolved')
            val,err,_=result
            total+=val
            error+=err
    except IntegrationWarning as exc:
        if context.error():
            raise ArithmeticError('HX compiled coupon callback unresolved: '+str(context.error())) from exc
        raise ArithmeticError('HX coupon survival integration unresolved') from exc
    if not (math.isfinite(total) and math.isfinite(error) and 0 <= total <= tau+error
            and error <= (len(cuts)-1)*max(1e-11*min(tau,1.),2e-10*abs(total))):
        raise ArithmeticError('HX coupon survival integral outside diagnostic budget')
    return total


def bond_value_compiled(p,asset,tau,asset_boundary):
    """Explicit experiment, never used by original bond/equity/control APIs."""
    b=asset_boundary
    if not (all(math.isfinite(z) for z in (asset,tau,b)) and asset>0 and b>0 and 0<=tau<=p.maturity):
        raise ValueError('Invalid compiled coupon bond state')
    recovery=p.recovery*b/p.maturity
    if asset<=b:return recovery
    if tau==0:return p.per_bond_principal
    x=_log_asset_ratio(asset,b)
    F,G=_first_passage_factors(p,x,tau)
    coupon=p.per_bond_coupon*coupon_annuity_compiled(p,x,tau) if p.per_bond_coupon else 0.
    return coupon+math.exp(-p.q*tau)*p.per_bond_principal*(1-F)+recovery*G
