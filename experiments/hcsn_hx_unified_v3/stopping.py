"""Separate neural stopping/renewal reference and QVI; not He--Xiong equity.

State dX = mu*dt + sigma*dW, discount rho > 0, FIRE pays X-K,
reset X=reset < K, mandatory deterministic refractory duration tau >= 0.
Infinite horizon, constant parameters; not coupled with task-model dynamics.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
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
    """Finite, strictly distinguishable f64 threshold of the one-shot oracle.

    A finite characteristic root does not imply 1/kappa or its sum with
    cost is representable. Do not return infinite or cost-rounded boundaries
    as if they solved the stopping problem.
    """
    displacement=1/p.kappa
    b=p.cost+displacement
    if not (math.isfinite(displacement) and math.isfinite(b) and b>p.cost):
        raise ArithmeticError('One-shot boundary unresolved in f64')
    return b


def one_shot_value(p: Stop, x: float) -> float:
    if not math.isfinite(x):
        raise ValueError('State must be finite')
    b=one_shot_boundary(p)
    value=x-p.cost if x>=b else (b-p.cost)*math.exp(-p.kappa*(b-x))
    if not math.isfinite(value):
        raise ArithmeticError('One-shot value unresolved in f64')
    return value


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
    """Independent scalar smooth-fit oracle, never a global QVI certificate.

    The legacy f64 Brent residual t+exp(-h-t)-1 loses the O(h) boundary
    separation at the Lambert-W branch point and can silently return cost.
    For small h, solve the *exponential* smooth-fit equation independently
    in adaptive-precision Decimal, without using the primary W or log-series
    inversion. For regular h solve the nondimensional smooth-fit displacement
    t, so Brent's relative tolerance is not amplified by a large cost offset.
    Reject unresolved f64 reward representation in either regime. This remains
    an offline diagnostic, not certification of the finance HX system.
    """
    k=p.kappa
    gap=p.cost-p.reset
    delay=p.discount*p.refractory
    lost=k*gap
    if (not all(math.isfinite(v) for v in (k,gap,delay,lost))
            or k<=0 or gap<=0 or lost<=0
            or (p.refractory>0 and delay<=0)):
        raise ArithmeticError('Independent renewal exponent unresolved in f64')
    h=math.fsum((lost,delay))
    if not math.isfinite(h) or h<=0:
        raise ArithmeticError('Independent renewal exponent unresolved in f64')
    if h <= 1e-4:
        with localcontext() as ctx:
            # At small h the exponential smooth-fit residual is O(h), while
            # the root is O(sqrt(h)). Use enough decimal places to resolve
            # the former, including legal subnormal binary64 loss scales.
            ctx.prec=max(90,int(-math.log10(h))+85)
            d=Decimal.from_float
            hd=d(k)*(d(p.cost)-d(p.reset))+d(p.discount)*d(p.refractory)
            if not hd>0:
                raise ArithmeticError('Non-positive independent renewal loss')
            t=(2*hd).sqrt()
            for _ in range(20):
                e=(-(hd+t)).exp()
                slope=1-e
                if slope<=0:
                    raise ArithmeticError('Unresolved independent smooth-fit slope')
                move=(t+e-1)/slope
                t-=move
                if abs(move)<Decimal(10)**(-ctx.prec+20):
                    break
            if not 0<t<1:
                raise ArithmeticError('Independent root outside proper renewal domain')
            if abs(t+(-(hd+t)).exp()-1)>Decimal(10)**(-ctx.prec+15):
                raise ArithmeticError('Independent smooth-fit residual unresolved')
            displacement=float(t/d(k))
            boundary=float(d(p.cost)+t/d(k))
    else:
        # Solve dimensionless t=k*(b-cost), not large absolute b. Brent's
        # rtol on b could exceed the entire displacement for a large cost.
        # expm1 preserves the strictly negative left residual at h>0.
        def residual(t):
            return t+math.expm1(-h-t)
        if not residual(0.)<0:
            raise ArithmeticError('Independent dimensionless root left bracket invalid')
        # Roundoff may erase the strictly positive residual at t=1 for
        # very large h. Refuse instead of treating rounded t=1 as interior.
        if residual(1.)<=0:
            raise ArithmeticError('Independent dimensionless root right bracket unresolved')
        t=brentq(residual,0.,1.,xtol=5e-15,rtol=8e-15)
        if not math.isfinite(t) or not 0<t<1:
            raise ArithmeticError('Independent dimensionless root unresolved')
        displacement=t/k
        boundary=p.cost+displacement
    # For either branch, b>cost alone is insufficient: if one cost ULP
    # materially exceeds the firing reward resolution, refuse explicitly.
    # This is a numerical admission policy, not a certified interval bound.
    if (not math.isfinite(boundary) or not boundary>p.cost
            or not math.isfinite(displacement) or displacement<=0
            or math.ulp(boundary)>1e-8*displacement):
        raise ArithmeticError('Independent boundary resolution unresolved at cost scale')
    return boundary

def _obstacle_from_value(p: Stop, x: float, b: float, val: float) -> float:
    """Stable exact *fixed-threshold* obstacle identity, not an optimality proof.

    For x<b, D*V(reset)/V(x) = exp(-rho*tau-kappa*(x-reset)).
    Subtracting D*V(reset)-V(x) directly loses O(1) obstacle values when
    V(x) is large. The expm1 factor preserves small renewal differences.
    For x>=b, the threshold policy fires immediately, so the obstacle is
    exactly zero by construction; this does not verify an optimal policy.
    Deep below reset, V(x) underflows while expm1(-h) overflows even if
    D*V(reset)-V(x) is finite. In that far tail, compute the two bounded
    continuation values separately; their ratio exceeds exp(36), so the
    subtraction is not the near-reset cancellation that expm1 protects.
    """
    if x>=b:
        return 0.0
    h=math.fsum((p.discount*p.refractory,p.kappa*(x-p.reset)))
    if not math.isfinite(h):
        raise ArithmeticError('Renewal obstacle exponent unresolved in f64')
    try:
        if h < -36.:
            # Since rho*tau >= 0 and kappa > 0, h<0 entails x<reset.
            # Here V(x)/(D*V(reset)) = exp(h) < exp(-36), so a direct
            # difference avoids 0*infinity without cancellation.
            discounted_reset=p.delay_discount*regenerative_value(p,p.reset,boundary=b)
            delta=math.fsum((discounted_reset,-val))
        else:
            delta=val*math.expm1(-h)
        obstacle=math.fsum((x-p.cost,delta))
    except (OverflowError, ValueError) as exc:
        raise ArithmeticError('Renewal obstacle subtraction unresolved') from exc
    if not math.isfinite(obstacle):
        raise ArithmeticError('Renewal obstacle outside finite f64 domain')
    return obstacle


def regenerative_obstacle(p: Stop, x: float, *, boundary: float | None = None) -> float:
    """Read out the fixed-threshold intervention residual without cancellation.

    Structural policy evidence only; a small obstacle alone never closes QVI.
    """
    b=regenerative_boundary(p) if boundary is None else boundary
    val=regenerative_value(p,x,boundary=b)
    return _obstacle_from_value(p,x,b,val)


def qvi(p: Stop, x: float, *, boundary: float | None = None) -> dict[str,float|bool]:
    """Sampled QVI; refuse unresolvable absolute generator error.

    This verifies finite diagnostics in its stated f64 domain, not an
    interval-certified coupled QVI. Continuation residuals above 1e-9
    cannot be passed off as zero merely because model values are huge.
    """
    b=regenerative_boundary(p) if boundary is None else boundary
    if not (math.isfinite(x) and math.isfinite(b) and b>p.cost and b>p.reset):
        raise ValueError('Invalid QVI input')
    val=regenerative_value(p,x,boundary=b)
    obstacle=_obstacle_from_value(p,x,b,val)
    if x<b:
        k=p.kappa
        # (sigma*k)^2/2 preserves a finite term when sigma**2 or k**2
        # would individually overflow/underflow. math.fsum mitigates the
        # cancellation of mu*k + diffusion_term - discount.
        noise=p.diffusion*k/math.sqrt(2.)
        contributions=(p.drift*k,noise*noise,-p.discount)
        if not all(math.isfinite(v) for v in contributions):
            raise ArithmeticError('Continuation generator terms unresolved')
        residual=math.fsum(contributions)
        generator=residual*val
        if not math.isfinite(generator) or abs(generator)>1e-9:
            raise ArithmeticError('Continuation generator not resolved at 1e-9 absolute scale')
    else:
        generator=p.drift-p.discount*val
        if not math.isfinite(generator):
            raise ArithmeticError('Firing-region generator unresolved in f64')
    return dict(value=val,obstacle=obstacle,generator=generator,
                complementarity=max(obstacle,generator),fire=x>=b)
