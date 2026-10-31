"""HX endogenous *algebraic smooth-fit* root from independent cash-flow integration.

A fixed candidate b enters the maturity-T representative-bond cash flow through
recovery(b). For log asset y=log(A/b), discount r, exponent eta>1, the killed
log-diffusion derivative at zero vanishes iff
  I(b) = integral_0^inf exp(-eta*y)[delta*b*exp(y)+B(b*exp(y);b)-C]dy = 0.
The first-hit bond B is computed by integrating the Brownian first-hit density;
Eq.(8), Eq.(12), Eq.(A7), and their helper functions are not used here.
The b-dependence is AFFINE: I(b)=slope*b+offset. Solve numerically integrated
coefficients and report *nonrigorous* quadrature convergence and an explicit
analytic envelope on omitted first-hit tail. Positive root != valid obstacle.
"""
from dataclasses import dataclass
import math

from scipy.special import roots_legendre, log_ndtr
from .hx_obstacle_grid_independent import (bond_from_first_hit, UnresolvedObstacle)


@dataclass(frozen=True)
class SmoothFitRoot:
    boundary: float
    slope: float
    offset: float
    first_hit_tail_bound: float
    first_hit_tail_log10_bound: float
    quadrature_shift: float
    log_cutoff: float
    nodes: int
    condition: str = 'Algebraic smooth-fit only; global obstacle NOT established'


def _calc_integral(p, nodes: int, cutoff: float):
    eta=(-(p.rate-p.payout-.5*p.volatility**2)
         +math.hypot(p.rate-p.payout-.5*p.volatility**2,
                     math.sqrt(2*p.rate)*p.volatility))/(p.volatility**2)
    if not (math.isfinite(eta) and eta>1+1e-8):
        raise UnresolvedObstacle('unresolved payout/transversality exponent')
    q=p.rate+p.shock_intensity*p.sale_fraction
    base=p.coupon/p.maturity/q
    par=p.principal/p.maturity
    const=(1-p.tax_shield)*p.coupon+par
    far=base+math.exp(-q*p.maturity)*(par-base)
    xs,ws=roots_legendre(nodes)
    slope=0.;offset=0.
    for x,w in zip(xs,ws):
        y=.5*cutoff*(float(x)+1)
        weight=.5*cutoff*float(w)*math.exp(-eta*y)
        ey=math.exp(y)
        bond1,_=bond_from_first_hit(p,ey,1.)
        bond2,_=bond_from_first_hit(p,2*ey,2.)
        coeff=bond2-bond1
        slope+=weight*(p.payout*ey+coeff)
        offset+=weight*(bond1-coeff-const)
    # Free asset-payout and constant no-default cashflow tails integrate exactly.
    slope+=p.payout*math.exp(-(eta-1)*cutoff)/(eta-1)
    offset+=(far-const)*math.exp(-eta*cutoff)/eta
    return slope,offset,eta,base,par


def independent_smoothfit_root(p, *, nodes: int=128,
                               log_cutoff: float=14.) -> SmoothFitRoot:
    """Independent algebraic root only, NOT a financial stopping certificate.

    An empirical Gauss-Legendre 2x-node discrepancy is reported, not promoted
    to a rigorous quadrature bound. First-hit omission is bounded separately.
    """
    if type(nodes) is not int or not (32<=nodes<=512) or nodes%2:
        raise UnresolvedObstacle('invalid even quadrature nodes')
    if (type(log_cutoff) not in (int,float) or not math.isfinite(log_cutoff)
            or not 7<=log_cutoff<=24):
        raise UnresolvedObstacle('unsupported log tail cutoff')
    # Reuse the independent obstacle module's structural input validation
    # without invoking its candidate free-boundary or any analytical HX code.
    from .hx_obstacle_grid_independent import _validate
    _validate(p,1.,3.6,33)
    s,o,eta,base,par=_calc_integral(p,nodes,log_cutoff)
    s2,o2,_,_,_=_calc_integral(p,nodes*2,log_cutoff)
    if not all(math.isfinite(v) for v in (s,o,s2,o2)) or s<=1e-14 or s2<=1e-14:
        raise UnresolvedObstacle('unresolved smooth-fit contraction/denominator')
    b=-o/s
    b2=-o2/s2
    if not (math.isfinite(b) and math.isfinite(b2) and b>0 and b2>0):
        raise UnresolvedObstacle('no positive algebraic financial root')
    # For any y >= cutoff, monotone coupling of drift Brownian motion and
    # reflection gives P(hit by T) <= 2 Phi(-(cutoff-|mu|T)/(sigma sqrt(T))).
    mu=p.rate-p.payout-.5*p.volatility**2
    bound_y=log_cutoff-abs(mu)*p.maturity
    if bound_y<=0:
        raise UnresolvedObstacle('first-hit tail envelope cannot be bounded')
    z=bound_y/(p.volatility*math.sqrt(p.maturity))
    base_term=math.exp(-(p.rate+p.shock_intensity*p.sale_fraction)*p.maturity)*abs(par-base)
    pref=b*p.recovery/p.maturity+base+base_term
    if pref<=0:
        raise UnresolvedObstacle('nonpositive tail envelope coefficient')
    log_tail=(math.log(pref)+math.log(2.)+float(log_ndtr(-z))
              -eta*log_cutoff-math.log(eta))
    tail=math.exp(log_tail) if log_tail>-744 else 0.0
    if not (math.isfinite(log_tail) and math.isfinite(abs(b2-b))):
        raise UnresolvedObstacle('invalid tail or numerical sensitivity')
    return SmoothFitRoot(b,s,o,tail,log_tail/math.log(10.),abs(b2-b),log_cutoff,nodes)
