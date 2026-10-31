"""One upper boundary for dX=mu*dt+sigma*dW; coefficients are held fixed.

Distance is boundary minus initial position. A boundary b(t)=b(0)+slope*t
is handled exactly by replacing mu with mu-slope. OU drift, nonlinear moving
boundaries, shared noise and interacting cells are outside this kernel's scope.
Probabilities may underflow; log probabilities preserve representable tails.
"""

import math

import numpy as np
from scipy.integrate import quad
from scipy.special import erfcx, exprel, log_ndtr, ndtri


class DomainError(ValueError):
    """The requested model or dimensionless scale is outside the stated domain."""


def _check(distance, drift, sigma, time):
    values = (distance, drift, sigma, time)
    if not all(math.isfinite(v) for v in values):
        raise DomainError("Finite scalar inputs required")
    if distance <= 0 or sigma <= 0 or time < 0:
        raise DomainError("Positive distance/noise and nonnegative time required")
    if not math.isfinite(sigma * sigma) or sigma * sigma == 0:
        raise DomainError("Noise variance is not representable in float64")
    if time:
        scale = sigma * math.sqrt(time)
        if not math.isfinite(scale) or scale == 0:
            raise DomainError("Diffusion scale is not representable in float64")
        a, v = distance / scale, drift * time / scale
        if not math.isfinite(a + abs(v)) or max(a, abs(v)) > 1e6:
            raise DomainError("Dimensionless distance/drift must not exceed 1e6")
        return a, v, scale
    return None


def _log_complement(log_probability):
    if log_probability == -math.inf:
        return 0.0
    if log_probability > 0:
        raise ArithmeticError("Positive log probability; no silent clipping")
    if log_probability == 0:
        return -math.inf
    return math.log(-math.expm1(log_probability)) if log_probability > -math.log(2) else math.log1p(-math.exp(log_probability))


def first_hit(distance, drift, sigma, time, *, boundary_slope=0.0):
    """Return F,f,logF,logS for the first hit, without a reset or time atom.

    The reflected term uses erfcx to avoid cancellation between a large
    exponential and a tiny normal tail. S uses its own log difference; when
    that subtraction is ill-conditioned, a positive integral resolves the
    boundary layer. Quadrature is numerically checked, not interval certified.
    No numerical probability is normalized/clipped.
    """
    if not math.isfinite(boundary_slope):
        raise DomainError("Finite affine-boundary slope required")
    mu = drift - boundary_slope
    checked = _check(distance, mu, sigma, time)
    if checked is None:
        return dict(probability=0.0, density=0.0, log_probability=-math.inf,
                    survival=1.0, log_survival=0.0, reflected_probability=0.0)
    a, v, scale = checked
    z, w = v - a, -v - a
    log_first = float(log_ndtr(z))
    if w <= 0:
        log_reflected = -.5 * z * z + math.log(.5 * float(erfcx(-w / math.sqrt(2))))
    else:
        log_reflected = 2 * v * a + float(log_ndtr(w))
    log_f = float(np.logaddexp(log_first, log_reflected))
    if log_f < -math.log(2):
        log_s = _log_complement(log_f)
    else:
        log_free_survival = float(log_ndtr(-z))
        difference = log_reflected - log_free_survival
        if difference > -1e-3:
            # Near the boundary two individually accurate log-CDFs can agree
            # to all their bits. Never subtract them to recover a tiny mass.
            log_a = math.log(a) if a else math.log(distance)-math.log(scale)
            if v < 0:
                # S = [Phi(a-v)-Phi(-a-v)] + (1-exp(2av))*Phi(-a-v).
                integral, error = quad(lambda u: math.exp(v*a*u-.5*(a*u)**2),
                                       -1., 1., epsabs=1e-13, epsrel=2e-13)
                log_interval = log_a-.5*v*v-.5*math.log(2*math.pi)+math.log(integral)
                # Factoring x out of 1-exp(-x) retains its logarithm even
                # when the float64 product x=2*a*abs(v) underflows.
                log_defect = (math.log(2.)+log_a+math.log(-v)
                              +math.log(float(exprel(2*a*v)))+float(log_ndtr(w)))
                log_s = float(np.logaddexp(log_interval, log_defect))
            else:
                # Integrate the positive killed density, with y=scale*u.
                # Rescaling by max(1,v-a) resolves the large-positive-drift
                # boundary layer while the integral remains of order one.
                c = v-a
                integration_scale = 1/max(1., c)
                def integrand(u):
                    y = integration_scale*u
                    return u*math.exp(-c*y-.5*y*y)*float(exprel(-2*a*y))
                integral, error = quad(integrand, 0., math.inf,
                                       epsabs=1e-13, epsrel=2e-13, limit=200)
                log_s = (-.5*c*c-.5*math.log(2*math.pi)+math.log(2.)+log_a
                         +2*math.log(integration_scale)+math.log(integral))
            if not math.isfinite(integral) or integral <= 0 or error > 1e-11*integral:
                raise ArithmeticError("Positive survival quadrature unresolved")
        else:
            log_s = log_free_survival + math.log(-math.expm1(difference))
        log_f = _log_complement(log_s)
    log_density = math.log(distance) - math.log(scale) - math.log(time) - .5 * math.log(2 * math.pi) - .5 * z * z
    if log_density > math.log(np.finfo(float).max):
        raise DomainError("First-hit density is not representable in float64")
    return dict(probability=math.exp(log_f), density=math.exp(log_density),
                log_probability=log_f, survival=math.exp(log_s), log_survival=log_s,
                reflected_probability=math.exp(log_reflected))


def first_hit_gradient(distance, drift, sigma, time, *, boundary_slope=0.0):
    """Analytic CDF derivatives; no claim about a sampled hard-event gradient."""
    row = first_hit(distance, drift, sigma, time, boundary_slope=boundary_slope)
    if time == 0:
        return dict(distance=0.0, drift=0.0, sigma=0.0, time=0.0, boundary_slope=0.0)
    mu = drift - boundary_slope
    scale = sigma * math.sqrt(time)
    z = (mu * time - distance) / scale
    density_normal = math.exp(-.5 * z * z) / math.sqrt(2 * math.pi)
    reflected = row["reflected_probability"]
    drift_gradient = 2 * distance * reflected / sigma**2
    gradient = dict(distance=-2 * density_normal / scale + 2 * mu * reflected / sigma**2,
                    drift=drift_gradient,
                    sigma=2 * distance / sigma * (density_normal / scale - 2 * mu * reflected / sigma**2),
                    time=row["density"], boundary_slope=-drift_gradient)
    if not all(math.isfinite(value) for value in gradient.values()):
        raise DomainError("First-hit gradient is not representable in float64")
    return gradient


def discounted_hit(distance, drift, sigma, time, discount, *, boundary_slope=0.0):
    """G=E[exp(-discount*tau) 1{tau<=time}], with a stable log value."""
    if not math.isfinite(discount) or discount < 0:
        raise DomainError("Finite nonnegative discount required")
    mu = drift - boundary_slope
    _check(distance, mu, sigma, time)
    if discount == 0:
        row = first_hit(distance, mu, sigma, time)
        return dict(value=row["probability"], log_value=row["log_probability"])
    transformed = math.hypot(mu, math.sqrt(2 * discount) * sigma)
    exponent = (-2 * discount * distance / (mu + transformed) if mu >= 0
                else (mu - transformed) * distance / sigma**2)
    log_value = exponent + first_hit(distance, transformed, sigma, time)["log_probability"]
    return dict(value=math.exp(log_value), log_value=log_value)


def killed_density(distance, remaining_gap, drift, sigma, time):
    """Subthreshold density in the positive gap coordinate, without reset.

    Reflection/free-density ratio is exp(-2*distance*gap/(sigma^2*time)).
    This factorization avoids cancellation at an absorbing boundary.
    """
    _check(distance, drift, sigma, time)
    if not math.isfinite(remaining_gap) or remaining_gap < 0 or time <= 0:
        raise DomainError("Finite nonnegative remaining gap and positive time required")
    if remaining_gap == 0:
        return 0.0
    scale = sigma * math.sqrt(time)
    z = (remaining_gap - distance + drift * time) / scale
    attenuation = -2 * (distance / scale) * (remaining_gap / scale)
    log_value = -.5 * z * z - math.log(scale) - .5 * math.log(2 * math.pi)
    log_value += math.log(-math.expm1(attenuation))
    return math.exp(log_value)


def two_segment_first_hit(distance, first, second, *, boundary_jump=0.0, tail_tolerance=1e-13):
    """Compose two (duration, drift-relative-to-boundary, sigma) segments.

    Each segment may have its own affine boundary slope already subtracted
    from drift. A negative jump lowers the boundary and causes immediate
    events. This is positive quadrature of the killed law, not grid remapping.
    Quadrature error is estimated; the Gaussian tail bound is analytic.
    """
    if len(first) != 3 or len(second) != 3 or not math.isfinite(boundary_jump):
        raise DomainError("Two fixed affine segments and a finite boundary jump required")
    t1, mu1, s1 = first
    t2, mu2, s2 = second
    _check(distance, mu1, s1, t1)
    _check(distance, mu2, s2, t2)
    if t1 <= 0 or not 1e-15 <= tail_tolerance <= 1e-6:
        raise DomainError("Positive first duration and tail tolerance in [1e-15,1e-6] required")
    initial = first_hit(distance, mu1, s1, t1)["probability"]
    scale = s1 * math.sqrt(t1)
    mean_gap = distance - mu1 * t1
    # Integrate in the first endpoint's Gaussian coordinate. The second
    # passage CDF can vary on a much smaller scale than this endpoint law;
    # its transition must be a panel boundary even when it lies close to an
    # existing knot. Adaptive quadrature alone can miss that narrow strip.
    mean = mean_gap / scale
    radius = float(-ndtri(tail_tolerance / 2))
    lower, upper = max(-mean, -radius), radius
    jump_z = (-boundary_jump - mean_gap) / scale
    second_width = s2 * math.sqrt(t2) / scale
    crossing_z = jump_z + mu2 * t2 / scale
    points = [-8., -4., -1., 0., 1., 4., 8.]
    points += [crossing_z + k * second_width for k in (-16., -8., -4., -1., 0., 1., 4., 8., 16.)]
    if mu2 < 0:
        boundary_width = min(second_width, s2 * s2 / (-2 * mu2 * scale))
        points += [jump_z + k * boundary_width for k in (0., 1., 4., 8., 16.)]

    def density(z):
        return (math.exp(-.5 * z * z) / math.sqrt(2 * math.pi)
                * -math.expm1(-2 * (distance / scale) * (mean + z)))

    def integrate(fn, left, right):
        if right <= left:
            return 0.0, 0.0
        knots = sorted(set(z for z in points if left < z < right))
        return quad(fn, left, right, points=knots, epsabs=tail_tolerance, epsrel=1e-11, limit=250)

    immediate, err0 = integrate(density, lower, min(jump_z, upper))

    def integrand(z):
        gap = scale * (z - jump_z)
        return density(z) * first_hit(gap, mu2, s2, t2)["probability"]

    extra, err1 = (integrate(integrand, max(lower, jump_z), upper) if t2 else (0., 0.))
    probability = initial + immediate + extra
    if not 0 <= probability <= 1 + 4 * (err0 + err1 + tail_tolerance):
        raise ArithmeticError("Composed probability violates its numerical error budget")
    return dict(probability=probability, initial_hit=initial, jump_hit=immediate,
                later_hit=extra, quadrature_error_estimate=err0 + err1,
                omitted_mass_upper_bound=tail_tolerance, roundoff_included=False,
                integration_coordinate="standardized_killed_endpoint_with_second_transition")
