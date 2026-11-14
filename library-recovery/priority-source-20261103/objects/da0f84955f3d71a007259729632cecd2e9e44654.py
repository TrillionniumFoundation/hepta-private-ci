"""P0: positive-integrand F-G independent check for a fixed-barrier Brownian FPT.

Integrates directly E[(1-exp(-q*tau)) 1{tau<=T}], NEVER subtracts
already-rounded F and G. Math is exact for the *constant drift/fixed barrier*
model only. mpmath quadrature is NOT a certified rounding/error interval.
"""
from __future__ import annotations
from mpmath import mp
from fpt_reference import FPT, formula


def _finite_log_cuts(s0, kappa, dps):
    """Choose finite upper integration edge with real-valued absolute tail bound.

    The density in s has bound exp(|kappa|)*sqrt(2/pi)*exp(-s^2/2).
    This only bounds the discarded mathematical tail, NOT quadrature or f64 error.
    """
    desired=mp.power(10,-min(dps-12,200))
    s_end=max(s0,mp.mpf(6))
    while mp.exp(abs(kappa))*mp.erfc(s_end/mp.sqrt(2))>desired:
        s_end*=2
    y_end=mp.log(s_end/s0)
    cuts=[mp.mpf(0)]
    for v in (1,2,4,8,16,24,32,48,64,96,128,192,256,384,512):
        if mp.mpf(v)<y_end:
            cuts.append(mp.mpf(v))
    if y_end>0:cuts.append(y_end)
    tail=mp.exp(abs(kappa))*mp.erfc(s_end/mp.sqrt(2))
    return cuts,tail


def positive_gap(p: FPT, dps: int = 90):
    p.validate()
    if dps < 40 or dps > 250:
        raise ValueError('dps out of range')
    if p.x == 0 or p.horizon == 0 or p.discount == 0:
        return {'gap': '0.0', 'dps': dps, 'method': 'nonnegative_density_integral'}
    with mp.workdps(dps):
        x, mu, sigma, T, q = (mp.mpf(repr(v)) for v in
                              (p.x, p.drift, p.sigma, p.horizon, p.discount))
        s0 = x/(sigma*mp.sqrt(T))
        kappa = mu*x/sigma**2
        # Set s=s0*exp(y). The y-log transform makes t/T=exp(-2y),
        # resolving narrow near-boundary short-time risk without cancellation.
        amp = mp.sqrt(2/mp.pi)
        def integrand(y):
            ey = mp.exp(y)
            s = s0*ey
            dt_discount = -mp.expm1(-q*T/ey**2)
            return amp*s*mp.exp(-mp.mpf('0.5')*(s+kappa/s)**2)*dt_discount
        cuts,tail_bound=_finite_log_cuts(s0,kappa,dps)
        result = mp.quad(integrand,cuts)
        if not (mp.isfinite(result) and result > 0):
            raise ArithmeticError('positive risk gap unresolved')
        return {'gap':mp.nstr(result,dps-8),'dps':dps,
                'omitted_tail_absolute_upper_bound':mp.nstr(tail_bound,12),
                'quadrature_certified':False,
                'method':'nonnegative_density_integral'}


def truncated_hit_first_moment(p:FPT,dps:int=85):
    """Return E[tau 1(tau<=T)] from the positive hitting-time density."""
    p.validate()
    if p.x == 0 or p.horizon == 0:
        return '0.0'
    with mp.workdps(dps):
        x,mu,sigma,T=(mp.mpf(repr(v)) for v in
                      (p.x,p.drift,p.sigma,p.horizon))
        s0=x/(sigma*mp.sqrt(T))
        kappa=mu*x/sigma**2
        amp=mp.sqrt(2/mp.pi)
        def f(y):
            s=s0*mp.exp(y)
            return amp*s*mp.exp(-(s+kappa/s)**2/2)*T*mp.exp(-2*y)
        cuts,_=_finite_log_cuts(s0,kappa,dps)
        result=mp.quad(f,cuts)
        return mp.nstr(result,dps-8)


def compare_gap(p:FPT,dps:int=90):
    """Cross-check direct positive integral against two-term closed formulas."""
    p.validate()
    independent=positive_gap(p,dps)
    original=formula(p,dps)
    with mp.workdps(dps):
        a=mp.mpf(independent['gap'])
        b=mp.mpf(original['F_minus_G'])
        absolute=abs(a-b)
        if b == 0 and p.discount > 0 and p.x>0 and p.horizon>0:
            raise ArithmeticError('reference gap was rounded to zero')
        relative=absolute/max(abs(a),abs(b)) if a!=b else mp.zero
        return {'positive_gap':independent['gap'],
                'subtracted_high_precision_gap':original['F_minus_G'],
                'absolute_difference':mp.nstr(absolute,18),
                'relative_difference':mp.nstr(relative,18),
                'dps':dps,'certified_interval':False}
