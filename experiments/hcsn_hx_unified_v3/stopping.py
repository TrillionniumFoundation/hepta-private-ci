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
        # Rationalized formula avoids cancellation for positive large drift.
        scale=math.hypot(self.drift,math.sqrt(2*self.discount)*self.diffusion)
        return 2*self.discount/(scale+self.drift) if self.drift>=0 else (scale-self.drift)/(self.diffusion**2)

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
    if h <= 1e-3:
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
    # Immediate FIRE above the chosen threshold, followed by actual reset value.
    if x>=b:
        return x-p.cost+p.delay_discount*amplitude*hr
    return amplitude*math.exp(-p.kappa*(b-x))


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


def qvi(p: Stop, x: float, *, boundary: float | None = None) -> dict[str,float|bool]:
    """Classical max{L V-rho V, x-K + D V(reset)-V}=0 reference.

    The active right/left second derivatives are only used within their open
    regions; do not interpret the branch junction as a classical C2 point.
    """
    b=regenerative_boundary(p) if boundary is None else boundary
    if not (math.isfinite(x) and math.isfinite(b) and b>p.cost and b>p.reset):
        raise ValueError('Invalid QVI input')
    val=regenerative_value(p,x,boundary=b)
    reset_val=regenerative_value(p,p.reset,boundary=b)
    obstacle=x-p.cost+p.delay_discount*reset_val-val
    if x<b:
        generator=(p.drift*p.kappa + .5*p.diffusion**2*p.kappa**2 - p.discount)*val
    else:
        generator=p.drift-p.discount*val
    return dict(value=val,obstacle=obstacle,generator=generator,
                complementarity=max(obstacle,generator),fire=x>=b)
