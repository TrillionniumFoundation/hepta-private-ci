"""Independent finite-maturity He-Xiong bond/first-passage audit.

The first-passage integration is based on Brownian hitting-time density, not
HX's normal-CDF reflection formula. Finite-precision sampled evidence only.
Never grant production authority from this diagnostic reference.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import warnings

from scipy.integrate import IntegrationWarning, quad
from scipy.special import log_ndtr


@dataclass(frozen=True)
class Passage:
    probability: float
    discounted: float
    absolute_error_bound: float


def _check(x: float, drift: float, sigma: float, discount: float, horizon: float) -> None:
    if not all(math.isfinite(z) for z in (x, drift, sigma, discount, horizon)):
        raise ValueError('Non-finite first-passage input')
    if x <= 0 or sigma <= 0 or discount <= 0 or horizon <= 0:
        raise ValueError('Require x,sigma,discount,horizon>0')


def integrate_passage(x: float, *, drift: float, sigma: float,
                      discount: float, horizon: float) -> Passage:
    """Evaluate F=Pr(T<=h), G=E[exp(-qT) 1(T<=h)] independently.

    T is first time x+drift*t+sigma*W_t reaches 0, starting at x>0.
    Substitution u=x/(sigma sqrt(t)) removes the t^(-3/2) singularity:
    F = sqrt(2/pi) int_u0^inf exp[-.5(u+a/u)^2] du,
    G = sqrt(2/pi) int_u0^inf exp[-.5(u+a/u)^2-q*x^2/(sigma^2*u^2)]du,
    a=drift*x/sigma^2. No financial HX closed form appears here.
    """
    _check(x, drift, sigma, discount, horizon)
    scale = x/sigma
    u0 = scale / math.sqrt(horizon)
    if not math.isfinite(u0) or u0 == 0 or scale == 0:
        raise ArithmeticError('First-passage transformation outside resolved f64 domain')
    a = drift*x/(sigma*sigma)
    # Split the near-boundary layer at u=O(x/sigma). Integrating all the
    # way from u0 to infinity in one adaptive call can silently miss this
    # layer, report a tiny quadrature error, and return G~=F when x is tiny.
    # The small-u piece is integrated after v=u/(x/sigma), where the
    # discount exponent becomes -q/v^2 and remains numerically resolved.
    uc = max(u0,min(1.,max(.05,scale*256*(1+abs(drift)/sigma+math.sqrt(discount)))))
    def small(v, q):
        z = scale*v+(drift/sigma)/v
        logv = -.5*z*z-q/(v*v)
        return 0. if logv < -745 else scale*math.sqrt(2/math.pi)*math.exp(logv)
    def large(u, q):
        z = u+a/u
        logv = -.5*z*z-q*(scale/u)**2
        return 0. if logv < -745 else math.sqrt(2/math.pi)*math.exp(logv)
    with warnings.catch_warnings():
        warnings.simplefilter('error', IntegrationWarning)
        if uc > u0:
            uend = uc/scale
            vlo=1/math.sqrt(horizon)
            vcut=min(uend,max(vlo,8*(1+abs(drift)/sigma+math.sqrt(discount))))
            f0,fe0=quad(lambda v: small(v,0.),vlo,vcut,
                         epsabs=3e-13,epsrel=3e-12,limit=300)
            g0,ge0=quad(lambda v: small(v,discount),vlo,vcut,
                         epsabs=3e-13,epsrel=3e-12,limit=300)
            if uend>vcut:
                # For tiny log-distance, uend=uc/scale can be enormous.
                # A single quad(vcut,uend) misses the low-v correction to
                # the near-certain hit probability. Resolve all decades in
                # finite geometric panels instead of treating it as flat.
                start=vcut
                panels=0
                while start<uend:
                    stop=min(uend,start*16)
                    if stop<=start or panels>=512:
                        raise ArithmeticError('Small-v quadrature panel limit')
                    ff,eef=quad(lambda v: small(v,0.),start,stop,
                                epsabs=3e-13,epsrel=3e-12,limit=300)
                    gg,eeg=quad(lambda v: small(v,discount),start,stop,
                                epsabs=3e-13,epsrel=3e-12,limit=300)
                    f0+=ff;g0+=gg;fe0+=eef;ge0+=eeg
                    start=stop
                    panels+=1
        else:
            f0=g0=fe0=ge0=0.
        # A single quad(uc, infinity) can miss a narrow peak far from uc.
        # The exponent in large(u,q) is
        #   -u*u/2 - a - (a*a/2 + q*scale*scale)/u**2.
        # Its mode is (a*a+2*q*scale*scale)**(1/4), with curvature -4
        # at the mode.  Always isolate a fixed-width window around that
        # mode, even when the mode lies tens/hundreds of units from uc.
        # math.hypot avoids an intermediate overflow from squaring a.
        def peaked_integral(q):
            mode=math.sqrt(math.hypot(a,math.sqrt(2*q)*scale))
            cuts=[uc]
            for edge in (mode-8.,mode+8.):
                if math.isfinite(edge) and edge>cuts[-1]:
                    cuts.append(edge)
            cuts.append(math.inf)
            total=error=0.
            for lo,hi in zip(cuts,cuts[1:]):
                part,estimated_error=quad(lambda u: large(u,q),lo,hi,
                    epsabs=3e-13,epsrel=3e-12,limit=300)
                total+=part
                error+=estimated_error
            return total,error
        f1,fe1=peaked_integral(0.)
        g1,ge1=peaked_integral(discount)
    f, g=f0+f1,g0+g1
    fe,ge=fe0+fe1,ge0+ge1
    err = fe+ge+1e-13
    if not all(math.isfinite(z) for z in (f,g,err)):
        raise ArithmeticError('Nonfinite first-passage quadrature')
    if f < -err or f > 1+err or g < -err or g > f+err:
        raise ArithmeticError('First-passage probability ordering violated')
    return Passage(f,g,err)


def independent_bond(*, x: float, drift: float, sigma: float, discount: float,
                     horizon: float, coupon_per_bond: float, principal_per_bond: float,
                     recovery_per_bond: float) -> tuple[float, Passage]:
    """Bond by independent stopped cash-flow expectation, not Eq. (8) F/G.

    It discounts coupon flow until min(T,h), principal on survival, and
    recovery on early default. Boundary is exogenously fixed for this test.
    """
    vals=(coupon_per_bond,principal_per_bond,recovery_per_bond)
    if not all(math.isfinite(v) and v>=0 for v in vals):
        raise ValueError('Bond cashflows must be nonnegative and finite')
    fp = integrate_passage(x,drift=drift,sigma=sigma,
                           discount=discount,horizon=horizon)
    survival=1-fp.probability
    terminal=math.exp(-discount*horizon)*survival
    coupon_pv=coupon_per_bond*(1-fp.discounted-terminal)/discount
    bond=coupon_pv+principal_per_bond*terminal+recovery_per_bond*fp.discounted
    if not math.isfinite(bond) or bond < -2*fp.absolute_error_bound*sum(vals)/discount:
        raise ArithmeticError('Invalid discounted bond cash flow')
    return bond, fp


def reflected_passage(x: float, *, drift: float, sigma: float,
                       discount: float, horizon: float) -> Passage:
    """Independent normal-CDF route for differential validation of quadrature.

    The production integration target is HX.default_probability and
    HX.discounted_default_factor, not this duplicated analytic baseline.
    """
    _check(x,drift,sigma,discount,horizon)
    s2=sigma*sigma
    u=sigma*math.sqrt(horizon)
    z=math.hypot(drift,math.sqrt(2*discount)*sigma)
    # For small discount relative to drift**2/sigma**2, z-|drift|
    # is a tiny positive difference of nearly equal f64 numbers. Directly
    # computing (-drift-z) for negative drift (or -drift+z for positive
    # drift) loses the Laplace exponent and yields a false discrepancy with
    # the *more accurate* density quadrature. Rationalize that difference:
    # (z-|drift|)*(z+|drift|)=2*discount*sigma**2.
    delta=2*discount*s2/(z+abs(drift))
    if drift < 0:
        exponent_first=(z-drift)*x/s2
        exponent_second=-delta*x/s2
    else:
        exponent_first=delta*x/s2
        exponent_second=-(z+drift)*x/s2
    def tail(expo,arg):
        y=expo+float(log_ndtr(arg))
        if y > 709:
            raise ArithmeticError('Normal-tail multiplication overflows')
        return 0. if y < -745 else math.exp(y)
    f=tail(0,(-x-drift*horizon)/u)+tail(-2*drift*x/s2,(-x+drift*horizon)/u)
    g=tail(exponent_first,(-x-z*horizon)/u)+tail(exponent_second,(-x+z*horizon)/u)
    return Passage(f,g,0.)


def reference_sweep() -> dict:
    """Deterministic bounded-domain diagnostic, not all-parameter certification."""
    groups=[(.02,.25,.08),(-.04,.32,.09),(.2,.3,.11),(-.15,.5,.02),
            (-.01,.09,1e-4),(.035,.07,.7),(-.12,.15,.001),(.14,.35,1.2),
            (-.08,.65,1e-5),(.4,.45,.4),(-.3,.28,2.),(.1,.2,.002)]
    xvals=(.06,.4,1.5)
    horizons=(.25,2.,7.)
    maxf=maxg=0.
    worst=None
    count=0
    for drift,sigma,q in groups:
        for x in xvals:
            for horizon in horizons:
                n=integrate_passage(x,drift=drift,sigma=sigma,discount=q,horizon=horizon)
                a=reflected_passage(x,drift=drift,sigma=sigma,discount=q,horizon=horizon)
                ef=abs(n.probability-a.probability)
                eg=abs(n.discounted-a.discounted)
                if ef>maxf or eg>maxg:
                    worst=(drift,sigma,q,x,horizon,ef,eg)
                maxf=max(maxf,ef)
                maxg=max(maxg,eg)
                count+=1
    if max(maxf,maxg)>2e-10:
        raise AssertionError(f'Independent FPT disagreement {worst}')
    return {'count':count,'max_F_difference':maxf,
            'max_G_difference':maxg,'worst':worst,
            'scope':'bounded numerical check; no continuum/full-domain certificate'}

if __name__=='__main__':
    import json
    print(json.dumps(reference_sweep(),sort_keys=True,indent=2))
