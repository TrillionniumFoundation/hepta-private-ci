"""Independent references for the first-passage clock experiment.

This module deliberately does not import ``kernels``.  Its arithmetic reference
uses 100-digit Decimal arithmetic, an integrated Gaussian power series, and the
Laplace continued fraction for Gaussian tails; it does not call log_ndtr/erfcx.
Positive quadrature of the original first-passage/absorbed densities and an exact
inverse-Gaussian physical sampler provide separate, explicitly scoped checks.

The Decimal branch is a high-precision evaluation of the same mathematical
first-passage identities, not an independent proof of those identities.  The
quadrature and event sampler are the independent distribution references.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
import math

import numpy as np
from scipy.integrate import quad


DECIMAL_PRECISION = 100
_PI = Decimal(
    "3.141592653589793238462643383279502884197169399375105820974944592307816406286"
    "208998628034825342117067982148086513282306647093844609550582231725359408128"
)
_INF = Decimal("Infinity")
_NEG_INF = Decimal("-Infinity")


@dataclass(frozen=True)
class ReferenceParams:
    mu: float
    sigma: float
    cancel_rate: float


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _parameters(distance, time, mu, sigma, rate=0):
    values = tuple(_decimal(x) for x in (distance, time, mu, sigma, rate))
    d, t, _, s, q = values
    if not all(x.is_finite() for x in values):
        raise ValueError("reference inputs must be finite")
    if d < 0 or t < 0 or s <= 0 or q < 0:
        raise ValueError("distance/time/rate must be nonnegative; sigma positive")
    return values


def _logsum(a, b):
    if a == _NEG_INF:
        return b
    if b == _NEG_INF:
        return a
    high, low = max(a, b), min(a, b)
    if low - high < -300:
        return high
    return high + (1 + (low - high).exp()).ln()


def _logdifference(a, b):
    if b == _NEG_INF:
        return a
    if b >= a:
        raise ArithmeticError("positive reference difference lost at current precision")
    if b - a < -300:
        return a
    return a + (1 - (b - a).exp()).ln()


def _log_normal_lower(z):
    """Gaussian log CDF; no binary floating-point special functions.

    For z <= -12, adjacent convergents of Laplace's continued fraction bracket
    the Mills ratio.  Failure to meet the declared 1e-75 relative gap raises.
    For |z| < 12, direct integration of exp(-x*x/2) uses guard digits.
    """
    z = _decimal(z)
    root_two_pi = (2 * _PI).sqrt()
    if abs(z) >= 12:
        a = abs(z)
        convergents = []
        for depth in (128, 129, 256, 257, 512, 513):
            tail = Decimal(0)
            for numerator in range(depth, 0, -1):
                tail = Decimal(numerator) / (a + tail)
            convergents.append(1 / (a + tail))
            if len(convergents) % 2 == 0:
                low, high = sorted(convergents[-2:])
                if (high - low) / low < Decimal("1e-75"):
                    mills = (low + high) / 2
                    log_tail = -(a * a) / 2 - root_two_pi.ln() + mills.ln()
                    if z < 0:
                        return log_tail
                    if log_tail < -300:
                        return Decimal(0)
                    return (1 - log_tail.exp()).ln()
        raise ArithmeticError("Gaussian continued fraction did not meet its bound")
    term = z
    total = term
    factor = -(z * z) / 2
    for n in range(1, 2000):
        term *= factor * Decimal(2 * n - 1) / Decimal(n * (2 * n + 1))
        total += term
        if abs(term) < Decimal("1e-115"):
            return (Decimal("0.5") + total / root_two_pi).ln()
    raise ArithmeticError("Gaussian power series failed to converge")


def _log_hit(d, t, m, s, q):
    if d == 0:
        return Decimal(0)
    if t == 0:
        return _NEG_INF
    drift = (m * m + 2 * q * s * s).sqrt()
    scale = s * t.sqrt()
    first = (m - drift) * d / (s * s) + _log_normal_lower((drift * t - d) / scale)
    second = (m + drift) * d / (s * s) + _log_normal_lower((-drift * t - d) / scale)
    return _logsum(first, second)


def _log_survive(d, t, m, s):
    if d == 0:
        return _NEG_INF
    if t == 0:
        return Decimal(0)
    scale = s * t.sqrt()
    first = _log_normal_lower((d - m * t) / scale)
    image = 2 * m * d / (s * s) + _log_normal_lower((-m * t - d) / scale)
    return _logdifference(first, image)


def decimal_log_hit(distance, time, mu, sigma, rate=0):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        return float(_log_hit(*_parameters(distance, time, mu, sigma, rate)))


def decimal_log_survival(distance, time, mu, sigma):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, _ = _parameters(distance, time, mu, sigma)
        return float(_log_survive(d, t, m, s))


def decimal_outcome_law(distance, horizon, params):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, q = _parameters(
            distance, horizon, params.mu, params.sigma, params.cancel_rate
        )
        if d == 0:
            return np.array([1.0, 0.0, 0.0])
        if t == 0:
            return np.array([0.0, 1.0, 0.0])
        hit = _log_hit(d, t, m, s, q).exp()
        survive = (-q * t + _log_survive(d, t, m, s)).exp()
        cancel = Decimal(0) if q == 0 else 1 - hit - survive
        if cancel < 0:
            raise ArithmeticError("negative high-precision cancellation mass")
        return np.array([float(hit), float(survive), float(cancel)])


def _log_event(event, t, d, m, s, q):
    if d == 0:
        return Decimal(0) if event == "hit" and t == 0 else _NEG_INF
    if event == "hit":
        if t == 0:
            return _NEG_INF
        return (
            d.ln() - s.ln() - (2 * _PI).ln() / 2
            - Decimal("1.5") * t.ln()
            - (d - m * t) ** 2 / (2 * s * s * t) - q * t
        )
    if event == "cancel":
        return q.ln() - q * t + _log_survive(d, t, m, s) if q > 0 else _NEG_INF
    if event == "survive":
        return -q * t + _log_survive(d, t, m, s)
    if event == "no_hit":
        if q == 0:
            return _log_survive(d, t, m, s)
        return _logdifference(Decimal(0), _log_hit(d, t, m, s, q))
    raise ValueError("unknown event")


def decimal_log_event(event, time, distance, params):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, q = _parameters(
            distance, time, params.mu, params.sigma, params.cancel_rate
        )
        return float(_log_event(event, t, d, m, s, q))


def _five_point(function, values, index, step):
    samples = []
    for factor in (-2, -1, 1, 2):
        moved = list(values)
        moved[index] += factor * step
        samples.append(function(*moved))
    return (samples[0] - 8 * samples[1] + 8 * samples[2] - samples[3]) / (12 * step)


def _forward_five_point(function, values, index, step):
    samples = []
    for factor in range(5):
        moved = list(values)
        moved[index] += factor * step
        samples.append(function(*moved))
    return (-25 * samples[0] + 48 * samples[1] - 36 * samples[2]
            + 16 * samples[3] - 3 * samples[4]) / (12 * step)


def decimal_cdf_derivatives(distance, time, mu, sigma):
    """[distance, mu, sigma, time] derivatives by high-precision differences.

    Steps resolve the diffusion width, including sigma=1e-8 at mu*time=distance.
    Boundary derivatives of a point mass are intentionally outside this API.
    """
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, _ = _parameters(distance, time, mu, sigma)
        if d == 0 or t == 0:
            raise ValueError("interior derivative reference requires distance,time > 0")
        epsilon = Decimal("1e-7")
        width = s * t.sqrt()
        steps = (
            min(d / 4, width * epsilon),
            s / t.sqrt() * epsilon,
            s * epsilon,
            min(t * epsilon, width * epsilon / abs(m)) if m else t * epsilon,
        )
        values = (d, m, s, t)
        function = lambda dd, mm, ss, tt: _log_hit(dd, tt, mm, ss, Decimal(0)).exp()
        return np.array([
            float(_five_point(function, values, i, steps[i])) for i in range(4)
        ])


def decimal_score_event(event, time, distance, params):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, q = _parameters(
            distance, time, params.mu, params.sigma, params.cancel_rate
        )
        if _log_event(event, t, d, m, s, q) == _NEG_INF:
            raise ValueError("score of an impossible event is undefined")
        if d == 0:
            return np.zeros(3)
        epsilon = Decimal("1e-7")
        reference_time = max(t, Decimal("1e-12"))
        values = (m, s, q)
        function = lambda mm, ss, qq: _log_event(event, t, d, mm, ss, qq)
        result = [
            float(_five_point(function, values, 0, s / reference_time.sqrt() * epsilon)),
            float(_five_point(function, values, 1, s * epsilon)),
        ]
        if event == "no_hit":
            rate_step = epsilon / reference_time
            hit_function = lambda mm, ss, qq: _log_hit(d, t, mm, ss, qq).exp()
            hit_derivative = (
                _five_point(hit_function, values, 2, min(q / 4, rate_step)) if q else
                _forward_five_point(hit_function, values, 2, rate_step)
            )
            no_hit_probability = _log_event(event, t, d, m, s, q).exp()
            result.append(float(-hit_derivative / no_hit_probability))
        else:
            # These likelihoods contain -lambda*time and, only for cancellation,
            # log(lambda). This exact boundary derivative avoids a negative rate.
            result.append(float(1 / q - t if event == "cancel" else -t))
        return np.array(result)


def decimal_discounted_derivatives(distance, time, params):
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION + 40
        d, t, m, s, q = _parameters(
            distance, time, params.mu, params.sigma, params.cancel_rate
        )
        if d == 0 or t == 0:
            return np.zeros(3)
        epsilon = Decimal("1e-7")
        values = (m, s, q)
        function = lambda mm, ss, qq: _log_hit(d, t, mm, ss, qq).exp()
        result = [
            float(_five_point(function, values, 0, s / t.sqrt() * epsilon)),
            float(_five_point(function, values, 1, s * epsilon)),
        ]
        rate_step = epsilon / t
        derivative = (
            _five_point(function, values, 2, min(q / 4, rate_step)) if q else
            _forward_five_point(function, values, 2, rate_step)
        )
        result.append(float(derivative))
        return np.array(result)


def _survival_integral(distance, time, mu, sigma):
    if time == 0:
        return 1.0
    u = distance / (sigma * math.sqrt(time))
    ceiling = u - mu * math.sqrt(time) / sigma
    low, high = min(-12.0, ceiling - 12.0), min(12.0, ceiling)

    def density(z):
        return math.exp(-z * z / 2) / math.sqrt(2 * math.pi) * (
            -math.expm1(-2 * u * (ceiling - z))
        )

    return quad(density, low, high, epsabs=2e-12, epsrel=2e-12, limit=200)[0]


def quadrature_outcome_law(distance, horizon, params):
    """Positive original-density integrals, intended for the declared moderate grid.

    The Gaussian integral truncates standardized tails beyond 12. This is an
    absolute-mass reference, NOT an extreme-tail relative-error certificate.
    """
    d, t = float(distance), float(horizon)
    m, s, q = params.mu, params.sigma, params.cancel_rate
    if d == 0:
        return np.array([1.0, 0.0, 0.0])
    if t == 0:
        return np.array([0.0, 1.0, 0.0])

    def first_hit(z):
        if z <= 0:
            return 0.0
        log_density = (
            math.log(d / s) - .5 * math.log(2 * math.pi) - 1.5 * math.log(z)
            - (d - m * z) ** 2 / (2 * s * s * z) - q * z
        )
        return math.exp(log_density)

    hit = quad(first_hit, 0, t, epsabs=2e-11, epsrel=2e-11, limit=250)[0]
    survive = math.exp(-q * t) * _survival_integral(d, t, m, s)
    cancel = 0.0
    if q > 0:
        cancel = quad(
            lambda z: q * math.exp(-q * z) * _survival_integral(d, z, m, s),
            0, t, epsabs=2e-10, epsrel=2e-10, limit=200,
        )[0]
    return np.array([hit, survive, cancel])


def sample_competing_events(distance, horizon, params, count, seed):
    """Exact-law IG/Levy draws plus independent exponential cancellation.

    There is no Euler grid and no missed-crossing discretization.  For negative
    drift, hit probability exp(2*mu*distance/sigma^2) supplies the defective mass;
    conditional successful hit time has the positive-|mu| inverse-Gaussian law.
    """
    if distance <= 0 or horizon <= 0 or params.sigma <= 0 or params.cancel_rate < 0:
        raise ValueError("sampler requires a positive active distance/horizon/sigma")
    rng = np.random.default_rng(seed)
    m, s = params.mu, params.sigma
    if m == 0:
        hitting = (distance / (s * rng.standard_normal(count))) ** 2
    else:
        hitting = rng.wald(distance / abs(m), distance * distance / (s * s), count)
        if m < 0:
            succeeds = rng.random(count) < math.exp(2 * m * distance / (s * s))
            hitting[~succeeds] = np.inf
    cancellation = (
        rng.exponential(1 / params.cancel_rate, count)
        if params.cancel_rate > 0 else np.full(count, np.inf)
    )
    hit = (hitting <= horizon) & (hitting <= cancellation)
    cancel = (cancellation <= horizon) & (cancellation < hitting)
    survive = ~(hit | cancel)
    return np.array([hit.mean(), survive.mean(), cancel.mean()])


def shape_clock_negative_control(mu, sigma, rate, speed):
    """Stationary-shape coordinates and their unidentifiable clock direction.

    A stationary density would require an explicitly separate reinjection model;
    this helper does not turn cancellation into reset.
    """
    before = np.array([mu / sigma**2, rate / sigma**2])
    after = np.array([speed * mu / (speed * sigma**2), speed * rate / (speed * sigma**2)])
    jacobian = np.array([
        [1 / sigma**2, -2 * mu / sigma**3, 0],
        [0, -2 * rate / sigma**3, 1 / sigma**2],
    ])
    clock_direction = np.array([mu, sigma / 2, rate])
    return before, after, jacobian @ clock_direction
