"""Separate neural stopping/renewal reference and QVI; not He--Xiong equity.

State dX = mu*dt + sigma*dW, discount rho > 0, FIRE pays X-K,
reset X=reset < K, mandatory deterministic refractory duration tau >= 0.
Infinite horizon, constant parameters; not coupled with task-model dynamics.
"""

from dataclasses import dataclass
import math

from scipy.optimize import brentq
from scipy.special import lambertw


@dataclass(frozen=True)
class Stop:
    drift: float
    diffusion: float
    discount: float
    cost: float
    reset: float
    refractory: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError('Non-finite stopping parameter')
        if not (self.diffusion>0 and self.discount>0 and self.refractory>=0
                and self.reset<self.cost):
            raise ValueError('Require sigma,rho>0, refractory>=0, reset<cost')

    @property
    def kappa(self):
        """Positive diffusion characteristic root, with resolved f64 arithmetic.

        kappa solves drift*kappa + .5*diffusion**2*kappa**2 = discount.
        Form dimensionless drift/diffusion first: squaring a large finite
        diffusion, forming 2*discount, or adding two near-maximum drifts can
        overflow even when the true positive kappa is representable.
        All branches are algebraically equivalent in exact arithmetic.
        """
        noise = math.sqrt(2.) * math.sqrt(self.discount)
        scaled_drift = self.drift / self.diffusion
        if not math.isfinite(scaled_drift):
            # A positive drift dominates diffusion by >max_f64; the
            # volatility correction is below f64 relative resolution.
            if self.drift <= 0:
                raise ArithmeticError('Negative-drift kappa scale unresolved in f64')
            root = self.discount / self.drift
        else:
            scale = math.hypot(scaled_drift, noise)
            if self.drift < 0:
                # Avoid both sigma**2 overflow and (scale-mu) overflow.
                root = scale / self.diffusion - scaled_drift / self.diffusion
            elif self.drift == 0:
                root = noise / self.diffusion
            elif scaled_drift > noise:
                # Rationalize the small root in the drift-dominated regime.
                z = noise / scaled_drift
                root = (self.discount * (2 / (math.hypot(1., z) + 1))) / self.drift
            else:
                # Diffusion-dominated positive drift, with no subtraction.
                root = noise * (noise / (scale + scaled_drift)) / self.diffusion
        # Refuse nonrepresentable and severely quantized subnormal roots.
        # This is a necessary f64 resolution guard, not interval certification.
        if (not math.isfinite(root) or root <= 0
                or math.ulp(root) > 1e-9 * root):
            raise ArithmeticError('Stopping characteristic root unresolved in f64')
        return root

    @property
    def delay_discount(self):
        return math.exp(-self.discount*self.refractory)


def one_shot_boundary(p: Stop) -> float:
    return p.cost+1/p.kappa


def one_shot_value(p: Stop, x: float) -> float:
    if not math.isfinite(x):
        raise ValueError('State must be finite')
    b=one_shot_boundary(p)
    return x-p.cost if x>=b else (b-p.cost)*math.exp(-p.kappa*(b-x))


def regenerative_boundary(p: Stop) -> float:
    """Scalar renewal threshold; stable at Lambert-W's coalescing branch point.

    Write h=rho*tau+kappa*(cost-reset)>0. The threshold t=kappa*(b-cost)
    obeys h=-log(1-t)-t, with t in (0,1), equivalently
    t=1+W0(-exp(-h)/e). The direct W form loses h when exp(-h) rounds
    to 1, although the renewal discount remains strictly contractive.
    """
    k=p.kappa
    gap=p.cost-p.reset
    delay=p.discount*p.refractory
    lost=k*gap
    if (not all(math.isfinite(v) for v in (k,gap,delay,lost))
            or k<=0 or gap<=0 or lost<=0
            or (p.refractory>0 and delay<=0)):
        raise ArithmeticError('Renewal exponent outside resolved f64 domain')
    h=math.fsum((lost,delay))
    if not math.isfinite(h) or h<=0:
        raise ArithmeticError('Renewal exponent outside resolved f64 domain')
    if h <= 1e-4:
        # Coalescing W0/W-1 at -1/e. Use a positive series for the
        # cancellation-free inverse h=t²/2+t³/3+... .
        t=math.sqrt(2*h)
        for _ in range(8):
            power=t*t
            series=power/2
            for n in range(3,14):
                power*=t
                series+=power/n
            t-=(series-h)*(1-t)/t
            if not (0<t<1):
                raise ArithmeticError('Renewal branch-point inverse unresolved')
    else:
        t=1+float(lambertw(-math.exp(-h)/math.e,k=0).real)
    b=p.cost+t/k
    if not math.isfinite(b) or not b>p.cost:
        raise ArithmeticError('Non-positive or unresolved firing reward at boundary')
    return b


def regenerative_value(p: Stop, x: float, *, boundary: float | None = None) -> float:
    """Exact infinite-renewal expected discounted firing reward for a threshold."""
    if not math.isfinite(x):
        raise ValueError('State must be finite')
    b=regenerative_boundary(p) if boundary is None else boundary
    if not (math.isfinite(b) and b>p.cost and b>p.reset):
        raise ValueError('Threshold must exceed cost and reset')
    hr=math.exp(-p.kappa*(b-p.reset))
    denom=-math.expm1(-p.discount*p.refractory-p.kappa*(b-p.reset))
    if denom <= 0:
        raise ValueError('Renewal series not contractive')
    amplitude=(b-p.cost)/denom
    if not math.isfinite(amplitude):
        raise ArithmeticError('Regenerative reward amplitude unresolved in f64')
    # Immediate FIRE above the chosen threshold, followed by actual reset value.
    value=(x-p.cost+p.delay_discount*amplitude*hr if x>=b else
           amplitude*math.exp(-p.kappa*(b-x)))
    if not math.isfinite(value):
        raise ArithmeticError('Regenerative value unresolved in f64')
    return value


def regenerative_boundary_independent(p: Stop) -> float:
    """Numerically independent root of the smooth-fit boundary condition."""
    k=p.kappa
    def residual(b):
        return k*(b-p.cost)+p.delay_discount*math.exp(-k*(b-p.reset))-1
    left=p.cost
    right=p.cost+1/k
    if residual(left)>=0 or residual(right)<=0:
        raise ArithmeticError('Root bracket invalid')
    return brentq(residual,left,right,xtol=1e-13,rtol=1e-13)


def _continuation_obstacle(p: Stop, x: float, b: float,
                           *, optimal_boundary: bool) -> float:
    """Cancellation-safe intervention minus continuation, strictly below b.

    For y=b-x>0, k=kappa, A=(b-K)/(1-exp(-rho*tau-k*(b-r))),
    continuation A*exp(-k*y), and reset contribution A-(b-K):

        (M U-U)(x) = y*(k*A-1) - A*(expm1(-k*y)+k*y).

    The second term is nonpositive; evaluating x-K+D*U(r)-U(x)
    subtracts nearly equal huge values. Around k*y=0, factor the small
    positive remainder as (k*y)^2/2 * sum(2*z^n/(n+2)!), z=-k*y.
    Reorder using y*(-z)*(k*A)/2 to prevent intermediate z*z underflow.
    At the *endogenous* smooth-fit boundary k*A=1 analytically; refuse a
    resolved violation, then use that exact identity rather than a noisy
    float correction to the small quadratic obstacle. Arbitrary supplied
    thresholds must retain the correction and may be suboptimal.
    """
    k=p.kappa
    y=b-x
    z=-k*y
    exponent=-p.discount*p.refractory-k*(b-p.reset)
    denom=-math.expm1(exponent)
    amplitude=(b-p.cost)/denom if denom>0 else math.nan
    slope=k*amplitude
    if (not all(map(math.isfinite,(y,z,denom,amplitude,slope)))
            or y<=0 or z>=0 or amplitude<=0 or slope<=0):
        raise ArithmeticError('QVI continuation obstacle unresolved in f64')
    if z>=-.01:
        # expm1(z)-z = z*z/2 * (1+z/3+z*z/12+...). No
        # cancellation or premature z**2 underflow for small |z|.
        series=1.
        term=1.
        for degree in range(3,18):
            term*=z/degree
            series+=term
        penalty=(.5*y*(-z))*(slope*series)
    else:
        penalty=amplitude*(math.expm1(z)-z)
    if not math.isfinite(penalty) or penalty<=0:
        raise ArithmeticError('QVI strict continuation obstacle unresolved')
    # Numerical sign admission: one-ULP perturbations of k*A can create a
    # correction of order ulp(1)*y, even if the computed product equals 1.
    # The multiplier is a conservative *diagnostic*, not a certified enclosure
    # of the root algorithm or a global optimal-stopping proof.
    rounding_diagnostic=64*math.ulp(1.)*max(1.,abs(slope))*y
    if not math.isfinite(rounding_diagnostic):
        raise ArithmeticError('QVI obstacle rounding diagnostic overflow')
    if optimal_boundary:
        if abs(slope-1)>1e-8:
            raise ArithmeticError('QVI smooth-fit identity unresolved')
        if penalty<=rounding_diagnostic:
            raise ArithmeticError('QVI strict obstacle sign unresolved in f64')
        return -penalty
    obstacle=math.fsum(((slope-1)*y,-penalty))
    if not math.isfinite(obstacle):
        raise ArithmeticError('QVI obstacle outside finite f64 domain')
    if abs(obstacle)<=rounding_diagnostic:
        raise ArithmeticError('QVI supplied-boundary obstacle sign unresolved')
    return obstacle



def regenerative_obstacle(p: Stop, x: float, *, boundary: float | None = None) -> float:
    """Finite fixed-threshold (intervene - continue) diagnostic.

    This exposes the same strict, cancellation-safe branch used by ``qvi``.
    A zero in the immediate-FIRE region is an identity of the selected
    threshold policy, NOT evidence that the threshold is globally optimal.
    An explicit boundary preserves its genuine smooth-fit correction.
    Refusal at unresolved continuation signs is intentional; never clip it.
    """
    b=regenerative_boundary(p) if boundary is None else boundary
    if not (math.isfinite(x) and math.isfinite(b) and b>p.cost and b>p.reset):
        raise ValueError('Invalid stopping obstacle input')
    value=regenerative_value(p,x,boundary=b)
    if x>=b:
        return 0.0
    return _continuation_obstacle(p,x,b,optimal_boundary=boundary is None)


def qvi(p: Stop, x: float, *, boundary: float | None = None) -> dict[str,float|bool]:
    """Scalar max{L U-rho U, M U-U}=0 with stable branch identities.

    In continuation U=A*exp(k*(x-b)), and k solves exactly the
    characteristic ODE, so (L-rho)U=0 analytically. Forming sigma**2
    then multiplying by k**2 can overflow even when this identity is
    valid and U is finite. On the immediate-FIRE side M U=U by the
    threshold-policy value definition; use zero rather than cancellation.
    Neither identity certifies the coupled financial HX obstacle or f32.
    """
    b=regenerative_boundary(p) if boundary is None else boundary
    if not (math.isfinite(x) and math.isfinite(b) and b>p.cost and b>p.reset):
        raise ValueError('Invalid QVI input')
    val=regenerative_value(p,x,boundary=b)
    if not math.isfinite(val):
        raise ArithmeticError('QVI value outside finite f64 domain')
    if x<b:
        obstacle=_continuation_obstacle(p,x,b,optimal_boundary=boundary is None)
        generator=0.0  # exact continuation ODE, not a fragile f64 subtraction
    else:
        obstacle=0.0  # immediate-FIRE value equals its own intervention
        generator=p.drift-p.discount*val
    if not math.isfinite(generator):
        raise ArithmeticError('QVI generator outside finite f64 domain')
    return dict(value=val,obstacle=obstacle,generator=generator,
                complementarity=max(obstacle,generator),fire=x>=b)
