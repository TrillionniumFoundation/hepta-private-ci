"""P0 independent high-precision implementation of He-Xiong (2012) Eq (12).

This is the published endogenous default boundary *only*, not the full A7
closed-form equity expression and not regenerative neuromorphic dynamics.
Uses mpmath and an explicit removable-singularity limit at zero liquidity
premium (effective discount q=r).
"""
from __future__ import annotations
from mpmath import mp
from full_hx_numeric import HXCoupled


def published_boundary(p:HXCoupled,dps:int=90):
    p.validate()
    if not 50<=dps<=250:
        raise ValueError('invalid reference precision')
    with mp.workdps(dps):
        r,d,s,m,xi,k,alpha,pi,C,P=(mp.mpf(repr(v)) for v in (
            p.rate,p.payout,p.volatility,p.maturity,p.shock_intensity,
            p.sale_fraction,p.recovery_fraction,p.tax_shield,
            p.total_coupon,p.total_principal))
        q=r+xi*k
        coupon=C/m
        principal=P/m
        a=(r-d-s*s/2)/(s*s)
        z=mp.sqrt(a*a+2*r/(s*s))
        zhat=mp.sqrt(a*a+2*q/(s*s))
        eta=z-a
        if eta<=1:raise ArithmeticError('inadmissible eta <=1 for smooth pasting')
        phi=lambda v:mp.erfc(-v/mp.sqrt(2))/2
        phi_density=lambda v:mp.exp(-v*v/2)/mp.sqrt(2*mp.pi)
        w=s*mp.sqrt(m)
        def bfun(x):
            return mp.exp(-q*m)*(phi(x*w)-mp.exp(r*m)*phi(-z*w))/(z+x)
        def Bfun(x):
            denom=z+x
            if denom==0:
                # The x -> -z term is 0/0, and the numerator's derivative is
                # the well-defined limit. Needed when xi*k == 0 (q=r).
                return w*phi_density(-z*w)-z*w*w*phi(-z*w)
            numerator=phi(x*w)-mp.exp((z*z-x*x)*w*w/2)*phi(-z*w)
            return numerator/denom
        big_sum=Bfun(-zhat)+Bfun(zhat)
        small_sum=bfun(-a)+bfun(a)
        numerator=(((1-pi)*C+(1-mp.exp(-q*m))*(principal-coupon/q))/eta
                   +(principal-coupon/q)*small_sum+(coupon/q)*big_sum)
        denominator=d/(eta-1)+alpha/m*big_sum
        if not (mp.isfinite(numerator) and mp.isfinite(denominator) and
                numerator>0 and denominator>0):
            raise ArithmeticError('nonpositive/undefined endogenous HX boundary')
        bound=numerator/denominator
        if not mp.isfinite(bound) or bound<=0:
            raise ArithmeticError('no finite positive HX boundary')
        if alpha*bound>P:
            raise ArithmeticError('outside current research recovery<=principal screening policy')
        return {'boundary':mp.nstr(bound,dps-10),
                'a':mp.nstr(a,24),'eta':mp.nstr(eta,24),
                'q':mp.nstr(q,24),
                'zero_premium_removable_limit_used':bool(xi*k==0),
                'source':'He-Xiong (2012) published Eq (12)',
                'verified_full_equity_A7':False,
                'certified_all_parameter_domain':False}


def independent_comparison(p:HXCoupled,N=1600,dps=90,L=10.):
    from full_hx_numeric import solve_free_boundary
    analytic=published_boundary(p,dps)
    numeric=solve_free_boundary(p,N,L)
    with mp.workdps(dps):
        delta=abs(mp.mpf(analytic['boundary'])-mp.mpf(str(numeric['boundary'])))
    return {'analytic':analytic,'independent_fd':numeric,
            'absolute_boundary_disagreement':mp.nstr(delta,22),
            'confidence_scope':'finite-grid numerical agreement only, not A7 proof'}
