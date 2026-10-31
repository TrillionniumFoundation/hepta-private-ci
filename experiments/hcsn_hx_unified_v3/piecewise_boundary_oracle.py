"""Independent two-segment Brownian first-passage reference (research only).

The lower boundary is continuous: b(t)=b0+c1*t for t<=switch,
then b0+c1*switch+c2*(t-switch). No neural training, QVI, or FP interval
certification is implied by the deterministic high-precision quadrature.
"""
import mpmath as mp
from .moving_boundary_enclosure import FirstHit, _real, linear_boundary_first_hit


def two_segment_first_hit(x, b, mu, sigma, c1, c2, switch, T, q=0, *, dps=60):
    """Integrate the *absorbed* first-segment endpoint against segment two.

    Brownian drift and diffusion must be frozen across the two segments.
    A killed transition density excludes paths that fired and re-crossed.
    """
    if type(dps) is not int or not 50 <= dps <= 180:
        raise ValueError("dps outside [50,180]")
    with mp.workdps(dps + 15):
        x, b, mu, sigma, c1, c2, switch, T, q = map(
            _real, (x, b, mu, sigma, c1, c2, switch, T, q)
        )
        if sigma <= 0 or not 0 <= switch <= T or q < 0:
            raise ValueError("requires sigma>0, 0<=switch<=T, q>=0")
        a = x - b
        if a <= 0:
            return FirstHit(mp.mpf(1), mp.mpf(1))
        if T == 0:
            return FirstHit(mp.mpf(0), mp.mpf(0))
        if switch == 0:
            return linear_boundary_first_hit(x, b, mu, sigma, c2, T, q, dps=dps + 15)
        if switch == T or c1 == c2:
            return linear_boundary_first_hit(x, b, mu, sigma, c1, T, q, dps=dps + 15)

        first = linear_boundary_first_hit(x, b, mu, sigma, c1, switch, q, dps=dps + 15)
        nu1 = mu - c1
        variance = sigma**2 * switch
        root = mp.sqrt(2 * mp.pi * variance)
        decay = mp.exp(-nu1**2 * switch / (2 * sigma**2))

        def killed_density(y):
            if y <= 0:
                return mp.mpf(0)
            # Exponential tilt of the driftless method-of-images kernel.
            # -expm1 avoids cancellation close to the absorbing boundary.
            return (decay / root * mp.exp(nu1 * (y - a) / sigma**2
                    - (y - a)**2 / (2 * variance))
                    * (-mp.expm1(-2 * a * y / variance)))

        remaining = T - switch
        nu2 = mu - c2
        z2 = sigma * mp.sqrt(remaining)
        s2 = mp.sqrt(nu2**2 + 2*q*sigma**2)
        normal = lambda t: mp.erfc(-t/mp.sqrt(2))/2

        def first_hit_tail(y, drift):
            return (normal((-y-drift*remaining)/z2)
                    + mp.exp(-2*drift*y/sigma**2)
                    * normal((-y+drift*remaining)/z2))

        def second_F(y):
            return first_hit_tail(y, nu2)

        def second_G(y):
            if q == 0:
                return second_F(y)
            return mp.exp(-(nu2+s2)*y/sigma**2)*first_hit_tail(y, -s2)

        # Integrate over the entire surviving gap domain, with knots near
        # the Gaussian's mass; no finite-tail truncation or MC approximation.
        scale = sigma * mp.sqrt(switch)
        knots = sorted({mp.mpf(0), a/4, a/2, a, a+scale,
                        max(mp.mpf(0), a+nu1*switch),
                        max(mp.mpf(0), a+nu1*switch+4*scale)})
        knots.append(mp.inf)
        continuation_F = mp.quad(lambda y: killed_density(y)*second_F(y),
                                 knots)
        p = first.probability + continuation_F
        if q == 0:
            # Discount-free first-event weight equals probability *exactly*.
            g = p
        else:
            continuation_G = mp.quad(lambda y: killed_density(y)*second_G(y),
                                     knots)
            g = first.discounted + mp.exp(-q * switch) * continuation_G
        if not (mp.isfinite(p) and mp.isfinite(g) and 0 <= g <= p <= 1):
            raise ArithmeticError("invalid piecewise first-hit ordering")
        if q > 0:
            # Positive-discount first-hit loss must be resolvable at the
            # working precision. In exact arithmetic: 0<F-G<=F*(-expm1(-q*T)).
            # This detects cancellation and excessive apparent discount loss;
            # do not silently accept G==F or clip to this necessary bound.
            loss = p - g
            upper = p * (-mp.expm1(-q * T))
            if not (0 < g and 0 < loss <= upper):
                raise ArithmeticError("unresolved piecewise discount-loss interval")
        # The exact pathwise bracket is a useful independent self-check.
        low = linear_boundary_first_hit(x,b,mu,sigma,min(c1,c2),T,q,dps=dps+15)
        high = linear_boundary_first_hit(x,b,mu,sigma,max(c1,c2),T,q,dps=dps+15)
        if not (low.probability <= p <= high.probability
                and low.discounted <= g <= high.discounted):
            raise ArithmeticError("piecewise solution violates global slope bracket")
        return FirstHit(+p, +g)
