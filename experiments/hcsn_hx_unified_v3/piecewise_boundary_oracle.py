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
        # Standardize the absorbed endpoint as y=center+scale*z. Integrating
        # in unscaled y misses the entire Gaussian when switch is very small:
        # even adaptive quadrature can report zero while survival tends to 1.
        scale = sigma * mp.sqrt(switch)
        center = a + nu1 * switch
        variance = scale**2
        gaussian_norm = 1 / mp.sqrt(2 * mp.pi)

        def killed_standard(z):
            y = center + scale * z
            if y <= 0:
                return mp.mpf(0)
            # The Jacobian cancels the 1/scale density normalization.
            # The image factor is bounded in [0,1] for a,y>0.
            return (gaussian_norm * mp.exp(-z*z/2)
                    * (-mp.expm1(-2 * a * y / variance)))

        def integrate_continuation(continuation):
            lower = -center / scale
            # Explicit normal-mass panels cannot collapse onto a when the
            # first interval is narrower than the working mantissa.
            nodes = [lower]
            nodes.extend(k for k in map(mp.mpf, (-40,-12,-6,0,6,12,40))
                         if k > lower)
            nodes.append(mp.inf)
            return mp.quad(lambda z: killed_standard(z) *
                           continuation(center + scale*z), nodes)

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

        # No finite-tail truncation or Monte Carlo approximation: the
        # interval extends to +infinity in standardized coordinates.
        continuation_F = integrate_continuation(second_F)
        p = first.probability + continuation_F
        if q == 0:
            # Discount-free first-event weight equals probability *exactly*.
            g = p
        else:
            continuation_G = integrate_continuation(second_G)
            g = first.discounted + mp.exp(-q * switch) * continuation_G
        if not (mp.isfinite(p) and mp.isfinite(g) and 0 <= g <= p <= 1):
            raise ArithmeticError("invalid piecewise first-hit ordering")
        # The exact pathwise bracket is a useful independent self-check.
        low = linear_boundary_first_hit(x,b,mu,sigma,min(c1,c2),T,q,dps=dps+15)
        high = linear_boundary_first_hit(x,b,mu,sigma,max(c1,c2),T,q,dps=dps+15)
        if not (low.probability <= p <= high.probability
                and low.discounted <= g <= high.discounted):
            raise ArithmeticError("piecewise solution violates global slope bracket")
        return FirstHit(+p, +g)
