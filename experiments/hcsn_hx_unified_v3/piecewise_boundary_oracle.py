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
        # The surviving gap is Gaussian about mean_gap with standard
        # deviation scale. Integrating in y loses a narrow mode when
        # scale is tiny relative to the distance from the original gap.
        # In z=(y-mean_gap)/scale the killed density times dy has a
        # standard-normal envelope, even for remote/very narrow modes.
        scale = sigma * mp.sqrt(switch)
        mean_gap = a + nu1 * switch
        lower_z = -mean_gap / scale
        gaussian_norm = mp.sqrt(2 * mp.pi)

        def surviving_gap(z):
            y = mean_gap + scale * z
            if y <= 0:
                return mp.mpf(0)
            return (mp.exp(-z*z/2) / gaussian_norm
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
            # nu2+s2 cancels for negative drift and tiny sigma;
            # rationalize the exponent before dividing by sigma**2.
            rate = (2*q/(s2-nu2) if nu2 < 0 else
                    (nu2+s2)/sigma**2)
            return mp.exp(-rate*y)*first_hit_tail(y, -s2)

        # Integrate in a standardized normal window. Its omitted mass is
        # bounded by erfc(radius/sqrt(2)); unlike an arbitrary spatial
        # cutoff, that bound is independent of drift, scale, and F2.
        radius = mp.sqrt(2 * mp.log(10) * (dps + 30))
        tail_bound = mp.erfc(radius / mp.sqrt(2))
        if lower_z >= radius:
            raise ArithmeticError("unresolved surviving-gap tail")
        z_knots = sorted({-radius, radius, mp.mpf(-16), mp.mpf(-8),
                          mp.mpf(-4), mp.mpf(-1), mp.mpf(0),
                          mp.mpf(1), mp.mpf(4), mp.mpf(8),
                          mp.mpf(16)}
                         | ({lower_z} if -radius < lower_z < radius
                            else set()))
        continuation_F = mp.quad(
            lambda z: surviving_gap(z)*second_F(mean_gap+scale*z), z_knots)
        p = first.probability + continuation_F
        if q == 0:
            # Discount-free first-event weight equals probability *exactly*.
            g = p
        else:
            continuation_G = mp.quad(
                lambda z: surviving_gap(z)*second_G(mean_gap+scale*z),
                z_knots)
            g = first.discounted + mp.exp(-q * switch) * continuation_G
        # Do not silently certify a probability below the known tail
        # uncertainty; the integral is a research approximation, not an
        # outward-rounded interval certificate.
        if p <= tail_bound or (1 - p) <= tail_bound:
            raise ArithmeticError("unresolved normalized Gaussian tail")
        if not (mp.isfinite(p) and mp.isfinite(g) and 0 <= g <= p <= 1):
            raise ArithmeticError("invalid piecewise first-hit ordering")
        # The exact pathwise bracket is a useful independent self-check.
        low = linear_boundary_first_hit(x,b,mu,sigma,min(c1,c2),T,q,dps=dps+15)
        high = linear_boundary_first_hit(x,b,mu,sigma,max(c1,c2),T,q,dps=dps+15)
        if not (low.probability <= p <= high.probability
                and low.discounted <= g <= high.discounted):
            raise ArithmeticError("piecewise solution violates global slope bracket")
        return FirstHit(+p, +g)
