"""Independent high precision finite-horizon first passage research oracle.

A constant drift Brownian log-distance to a *fixed* absorbing barrier:
    dX = drift dt + sigma dW, X(0) = x >= 0.
F = P(hit <= horizon), G = E[exp(-discount * hit) 1(hit <= horizon)].
This module is NOT the coupled He-Xiong equity/rollover solution and does not
claim certified interval arithmetic or original repo integration.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from mpmath import mp


@dataclass(frozen=True)
class FPT:
    x: float
    drift: float
    sigma: float
    horizon: float
    discount: float

    def validate(self):
        vals = (self.x, self.drift, self.sigma, self.horizon, self.discount)
        if any(not math.isfinite(v) for v in vals):
            raise ValueError("nonfinite input")
        if self.x < 0 or self.sigma <= 0 or self.horizon < 0 or self.discount < 0:
            raise ValueError("requires x>=0,sigma>0,horizon>=0,discount>=0")


def _num(x):
    return mp.mpf(repr(x))


def _Phi(z):
    return mp.erfc(-z / mp.sqrt(2)) / 2


def _formula(x, drift, sigma, horizon, discount):
    if x == 0:
        return mp.one, mp.one
    if horizon == 0:
        return mp.zero, mp.zero
    a = drift / sigma**2
    z = mp.sqrt(a*a + 2*discount/sigma**2)
    u = sigma * mp.sqrt(horizon)
    h1, h2 = (-x-drift*horizon)/u, (-x+drift*horizon)/u
    F = _Phi(h1) + mp.exp(-2*a*x)*_Phi(h2)
    G = (mp.exp((-a+z)*x)*_Phi((-x-z*sigma**2*horizon)/u)
         + mp.exp((-a-z)*x)*_Phi((-x+z*sigma**2*horizon)/u))
    return F, G


def formula(p: FPT, dps=90):
    """Decimal string output prevents accidental conversion before comparison."""
    p.validate()
    if not 40 <= dps <= 250:
        raise ValueError("reference dps outside [40,250]")
    with mp.workdps(dps):
        f,g = _formula(*map(_num,(p.x,p.drift,p.sigma,p.horizon,p.discount)))
        if not (mp.isfinite(f) and mp.isfinite(g)):
            raise ArithmeticError("nonfinite high precision FPT result")
        # Rounded F=G at extreme precision is unresolved if q>0 and x,T>0.
        if not (0<=g<=f<=1):
            raise ArithmeticError("high precision physical ordering unresolved")
        if p.discount>0 and p.x>0 and p.horizon>0 and f==g:
            raise ArithmeticError("high precision F/G gap unresolved")
        return {'F':mp.nstr(f,dps-5),'G':mp.nstr(g,dps-5),
                'F_minus_G':mp.nstr(f-g,dps-5),'dps':dps}


def transformed_integral(p: FPT, dps=65):
    """Independent quadrature after s=x/(sigma sqrt(t)) change of variables.

    This removes the near-t=0 spike of the first hit density, but it is NOT
    a rigorous validated quadrature-error enclosure. Used as cross-check only.
    """
    p.validate()
    if p.x==0:
        return {'F':'1','G':'1'}
    if p.horizon==0:
        return {'F':'0','G':'0'}
    with mp.workdps(dps):
        x, mu, sig, tmax, q = map(_num,(p.x,p.drift,p.sigma,p.horizon,p.discount))
        s0=x/(sig*mp.sqrt(tmax))
        kappa=mu*x/(sig*sig)
        factor=mp.sqrt(2/mp.pi)
        def density_s(s, discount):
            return factor*mp.exp(-(s+kappa/s)**2/2 - discount*x*x/(sig*sig*s*s))
        def integrate(qv):
            cuts = [s0]
            for point in (mp.mpf('0.5'),mp.one,mp.mpf('2'),mp.mpf('5'),mp.mpf('10')):
                if point>s0:
                    cuts.append(point)
            cuts.append(mp.inf)
            return mp.quad(lambda s:density_s(s,qv),cuts)
        F,G=integrate(mp.zero),integrate(q)
        return {'F':mp.nstr(F,dps-6),'G':mp.nstr(G,dps-6)}


def float_diagnostic(p: FPT, dps=95):
    """Warn about f64 representational resolution; never silently clip F/G."""
    reference=formula(p,dps=dps)
    f,g=map(float,(reference['F'], reference['G']))
    gap=float(reference['F_minus_G'])
    ulp=math.ulp(max(abs(f),abs(g),2.0**-1022))
    # f64 closeness to physical ordering does NOT prove the true error bound.
    if not (0<=g<=f<=1):
        classification='DENY_NUMERIC_ORDER'
    elif p.x>0 and p.horizon>0 and p.discount>0 and gap<=32*ulp:
        classification='DENY_F64_UNRESOLVED_GAP'
    else:
        classification='REFERENCE_CHECK_ONLY'
    return {'reference':reference,'binary64_F':f,'binary64_G':g,
            'gap_ulp':gap/ulp if ulp else None,'classification':classification}


def boundary_derivatives(p: FPT, dps=85):
    """Independent analytic/automatic derivatives for a fixed-barrier case."""
    p.validate()
    if p.x<=0 or p.horizon<=0:
        raise ValueError("derivative check is only valid inside x,T>0")
    with mp.workdps(dps):
        x,mu,sig,t,q=map(_num,(p.x,p.drift,p.sigma,p.horizon,p.discount))
        u=sig*mp.sqrt(t)
        h1=(-x-mu*t)/u
        h2=(-x+mu*t)/u
        phi=lambda z: mp.exp(-z*z/2)/mp.sqrt(2*mp.pi)
        analytic=(-phi(h1)/u + mp.exp(-2*mu*x/sig**2)*
                  (-2*mu/sig**2*_Phi(h2)-phi(h2)/u))
        automatic=mp.diff(lambda xx:_formula(xx,mu,sig,t,q)[0],x)
        return {'analytic_dx_F':mp.nstr(analytic,45),
                'automatic_dx_F':mp.nstr(automatic,45),
                'abs_delta':mp.nstr(abs(analytic-automatic),20)}
