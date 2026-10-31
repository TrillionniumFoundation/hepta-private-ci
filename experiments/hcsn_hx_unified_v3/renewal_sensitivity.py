"""P0 research-only analytic Jacobian of the *scalar* regenerative boundary.

This concerns Stop's one-dimensional constant-coefficient Brownian renewal QVI.
It is NOT a Jacobian of the coupled He--Xiong financial barrier, a global QVI
certificate, an event-gradient theorem or a differentiable production kernel.

For k=positive root of mu*k + sigma**2*k**2/2=rho and b solving
k*(b-K) - 1 + exp(-rho*tau-k*(b-reset)) = 0,
let t=k*(b-K), q=1-t. Then db/dtheta follows by implicit differentiation.

Only strict numerically resolved f64 inputs are admitted. Near branch points,
extreme cancellation and unresolved characteristic discriminants fail closed.
"""

from dataclasses import dataclass
import math

from .stopping import Stop, regenerative_boundary


@dataclass(frozen=True)
class BoundarySensitivity:
    boundary: float
    kappa: float
    renewal_t: float
    discount_factor: float
    drift: float
    diffusion: float
    discount: float
    cost: float
    reset: float
    refractory: float


def regenerative_boundary_sensitivity(p: Stop) -> BoundarySensitivity:
    """Return local derivatives in Stop field order, or explicitly refuse.

    The f64 conditioning thresholds are *diagnostic policies*, not proven
    enclosures; changing the parameter domain can invalidate derivatives.
    At a boundary/obstacle switch no ordinary gradient is claimed.
    """
    k = p.kappa
    b = regenerative_boundary(p)
    gap = p.cost - p.reset
    reward = b - p.cost
    t = k * reward
    # A resolvable, non-coalescent branch gives 0<t<1, q=1-t, and
    # dt/dh=q/t. Refuse when rounding erases the firing reward, t or q.
    if (not all(map(math.isfinite, (k, b, gap, reward, t))) or
            min(k, gap, reward, t) <= 0 or
            t <= 1e-8 or t >= 1 - 1e-8 or
            math.ulp(b) > 1e-8 * reward):
        raise ArithmeticError('Renewal boundary sensitivity ill-conditioned in f64')

    q = 1 - t
    exponent = math.fsum((-p.discount * p.refractory, -k * (b - p.reset)))
    if not math.isfinite(exponent) or exponent >= 0:
        raise ArithmeticError('Renewal discount exponent unresolved')
    # A selected Lambert-W solution must also satisfy the *original*
    # smooth-fit equation. This is a finite accuracy check, not a certificate.
    q_independent = math.exp(exponent)
    if abs(q - q_independent) > 64 * math.ulp(1.0):
        raise ArithmeticError('Renewal smooth-fit residual unresolved')

    discriminant = math.hypot(p.drift,
                              (math.sqrt(2.0) * math.sqrt(p.discount)) * p.diffusion)
    if not math.isfinite(discriminant) or discriminant <= 0:
        raise ArithmeticError('Characteristic derivative unresolved')
    # d(t)/d(h)=(1-t)/t, h=k*(K-reset)+rho*refractory.
    dh_gain = q / t
    # b=K+t/k.  This avoids subtracting nearby value functions at b.
    db_dk = math.fsum((dh_gain * (gap / k), -(t / k) / k))
    dk_drift = -k / discriminant
    dk_diffusion = -(p.diffusion * k) * (k / discriminant)
    dk_discount = 1 / discriminant

    jacobian = (
        db_dk * dk_drift,
        db_dk * dk_diffusion,
        math.fsum((db_dk * dk_discount, dh_gain * (p.refractory / k))),
        1 / t,
        -dh_gain,
        dh_gain * (p.discount / k),
    )
    if not all(map(math.isfinite, jacobian)):
        raise ArithmeticError('Regenerative boundary derivative unresolved')
    return BoundarySensitivity(b, k, t, q, *jacobian)
