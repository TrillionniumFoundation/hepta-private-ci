"""Research-only exact linear first-hit and slope envelope; not an HX/QVI proof.

For X=x+mu*t+sigma*W and b(t)=b0+c*t, use relative drift mu-c.
A proven c_lo<=b'(t)<=c_hi implies pathwise first-hit bounds.
Results are high-precision approximations, NOT certified FP intervals.
"""
from collections import namedtuple
import mpmath as mp

FirstHit = namedtuple("FirstHit", "probability discounted")
FirstHitEnvelope = namedtuple("FirstHitEnvelope", "lower upper")


def _real(value):
    if isinstance(value, bool):
        raise ValueError("bool is not a real input")
    try:
        v = mp.mpf(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("input must be finite real") from exc
    if not mp.isfinite(v):
        raise ValueError("input must be finite real")
    return v


def linear_boundary_first_hit(x, b, mu, sigma, c, T, q=0, *, dps=100):
    """Return P(tau<=T) and E[exp(-q*tau) 1(tau<=T)]."""
    if type(dps) is not int or not 50 <= dps <= 300:
        raise ValueError("dps outside [50,300]")
    with mp.workdps(dps):
        x, b, mu, sigma, c, T, q = map(_real, (x, b, mu, sigma, c, T, q))
        if sigma <= 0 or T < 0 or q < 0:
            raise ValueError("requires sigma>0, T>=0, q>=0")
        gap = x-b
        if gap <= 0:
            return FirstHit(mp.mpf(1), mp.mpf(1))
        if T == 0:
            return FirstHit(mp.mpf(0), mp.mpf(0))
        nu = mu-c
        def F(drift):
            z = sigma*mp.sqrt(T)
            normal = lambda a: mp.erfc(-a/mp.sqrt(2))/2
            return normal((-gap-drift*T)/z) + mp.exp(-2*drift*gap/sigma**2)*normal((-gap+drift*T)/z)
        p = F(nu)
        s = mp.sqrt(nu**2+2*q*sigma**2)
        g = mp.exp(-(nu+s)*gap/sigma**2)*F(-s)
        if not (mp.isfinite(p) and mp.isfinite(g) and 0 <= g <= p <= 1):
            raise ArithmeticError("invalid first-hit probability ordering")
        # For a positive horizon, gap and discount, the stopped discount loss
        # D=E[(1-exp(-q*tau)) 1(tau<=T)] is strictly positive and at most
        # F(T)*(-expm1(-q*T)). F-G may silently lose significance even in mpf.
        # Reject unresolved rather than promoting false zero/oversized loss.
        if q > 0:
            loss = p - g
            upper = p * (-mp.expm1(-q * T))
            if not (0 < g and 0 < loss <= upper):
                raise ArithmeticError("unresolved discounted first-hit loss")
        return FirstHit(+p, +g)


def slope_bounded_first_hit(x, b, mu, sigma, c_lo, c_hi, T, q=0, *, dps=100):
    """Caller MUST prove derivative bounds for the whole observation window."""
    with mp.workdps(dps):
        if _real(c_lo) > _real(c_hi):
            raise ValueError("inverted boundary slope bounds")
        lo = linear_boundary_first_hit(x,b,mu,sigma,c_lo,T,q,dps=dps)
        hi = linear_boundary_first_hit(x,b,mu,sigma,c_hi,T,q,dps=dps)
        if lo.probability > hi.probability or lo.discounted > hi.discounted:
            raise ArithmeticError("slope envelope failed")
        return FirstHitEnvelope(lo,hi)
