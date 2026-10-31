"""Independent high-precision *time-domain* Brownian first-hit bond reference.

This intentionally avoids upstream HX bond Eq.(8), scipy normal CDF and
u=distance/(sigma*sqrt(t)) transform used by the production candidate.
Reference integral is directly in physical time t, with the first-passage
mode as a quadrature split. This is a high-precision empirical comparator,
NOT a rigorous interval enclosure or a proof for every legal parameter.
"""
from dataclasses import dataclass
import math
import mpmath as mp


class UnresolvedMP(ValueError):
    pass


@dataclass(frozen=True)
class MPBondReference:
    value: str
    hit_probability: str
    discounted_hit_factor: str
    digits: int


def bond_time_integral(p, asset: float, boundary: float, *, digits: int = 70) -> MPBondReference:
    """Physical t-density quadrature, split at Brownian first-hit density peak.

    Density: log(asset/b)/(sigma*sqrt(2*pi*t^3))
        *exp(-(log(asset/b)+(r-delta-sigma^2/2)*t)^2/(2*sigma^2*t)).
    """
    if type(digits) is not int or not 50 <= digits <= 130:
        raise UnresolvedMP('unsupported precision')
    vals=(p.rate,p.payout,p.volatility,p.maturity,p.principal,p.coupon,
          p.tax_shield,p.recovery,p.shock_intensity,p.sale_fraction,asset,boundary)
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in vals):
        raise UnresolvedMP('nonfinite inputs')
    if not (p.rate>0 and p.payout>=0 and p.volatility>0 and p.maturity>0
            and p.principal>0 and p.coupon>=0 and p.shock_intensity>=0
            and 0<=p.sale_fraction<=1 and 0<=p.recovery<=1
            and 0<=p.tax_shield<=1 and 0<boundary<asset):
        raise UnresolvedMP('invalid physical domain')
    # Convert finite double *decimal string* (not its unrepresentable ideal)
    # to arbitrary precision; the reference is explicitly relative to those
    # decimal parameters and cannot repair prior float input quantization.
    with mp.workdps(digits):
        m=lambda v: mp.mpf(str(v))
        v=mp.log(m(asset)/m(boundary))
        sigma=m(p.volatility)
        T=m(p.maturity)
        r=m(p.rate)
        drift=r-m(p.payout)-sigma*sigma/2
        q=r+m(p.shock_intensity)*m(p.sale_fraction)
        if not (v>0 and T>0 and q>0):
            raise UnresolvedMP('invalid discount or log state')
        # A robust split near the mode of the density: derivative of
        # -(v+mu*t)^2/(2*sigma^2*t)-3/2 log t yields quadratic in t.
        # mu^2*t^2 + 3*sigma^2*t - v^2 = 0. Use positive root.
        mu2=drift*drift
        mode=2*v*v/(3*sigma*sigma+mp.sqrt(9*sigma**4+4*mu2*v*v))
        def density(t):
            if t<=0:
                return mp.mpf('0')
            return v/(sigma*mp.sqrt(2*mp.pi*t**3))*mp.exp(
                -(v+drift*t)**2/(2*sigma*sigma*t))
        points=[mp.mpf('0')]
        if mode<T:
            points.append(mode)
        points.append(T)
        try:
            hit=mp.quad(density,points,method='tanh-sinh')
            discounted=mp.quad(lambda t:density(t)*mp.exp(-q*t),points,method='tanh-sinh')
        except (ValueError,OverflowError,ZeroDivisionError) as e:
            raise UnresolvedMP('time-density quadrature did not resolve') from e
        if not (mp.isfinite(hit) and mp.isfinite(discounted)
                and 0<=discounted<=hit<=1):
            raise UnresolvedMP('nonphysical first-hit integral')
        coupon=m(p.coupon)/T
        principal=m(p.principal)/T
        recovery=m(p.recovery)*m(boundary)/T
        base=coupon/q
        bond=base+mp.exp(-q*T)*(principal-base)*(1-hit)+(recovery-base)*discounted
        return MPBondReference(mp.nstr(bond,digits),mp.nstr(hit,digits),
                               mp.nstr(discounted,digits),digits)
