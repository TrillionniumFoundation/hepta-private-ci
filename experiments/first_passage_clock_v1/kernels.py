"""Stable constant-coefficient first-passage laws and event-likelihood scores.

``survive`` means observed absence of BOTH hit and cancellation. ``no_hit``
means only absence of an observed hit; unobserved cancellation is marginalized.
Probability, event density, and initial boundary atoms are kept distinct.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad
from scipy.special import erfcx, log_ndtr

LOG_SQRT_2PI = 0.5 * math.log(2 * math.pi)
SQRT_PI_OVER_2 = math.sqrt(math.pi / 2)


@dataclass(frozen=True)
class Params:
    mu: float
    sigma: float
    cancel_rate: float

    def validate(self):
        if not all(math.isfinite(x) for x in (self.mu, self.sigma, self.cancel_rate)):
            raise ValueError("non-finite physical parameter")
        if self.sigma <= 0 or self.cancel_rate < 0:
            raise ValueError("sigma must be positive and cancellation nonnegative")


def _validate(distance, time, mu, sigma):
    if not all(math.isfinite(x) for x in (distance, time, mu, sigma)):
        raise ValueError("non-finite kernel input")
    if distance < 0 or time < 0 or sigma <= 0:
        raise ValueError("nonnegative distance/time and positive sigma required")


def _log1mexp(value):
    if value > 0:
        raise ValueError("log probability exceeds zero")
    if value == 0:
        return -math.inf
    if value < -math.log(2):
        return math.log1p(-math.exp(value))
    return math.log(-math.expm1(value))


def _mills(value):
    return SQRT_PI_OVER_2 * float(erfcx(value / math.sqrt(2)))


def _mills_complement(value):
    """1 - value*M(value), avoiding subtraction of nearly equal numbers."""
    if value < 24:
        return 1 - value * _mills(value)
    inverse_square = 1 / (value * value)
    term = inverse_square
    total = term
    for n in range(1, 100):
        following = -term * (2 * n + 1) * inverse_square
        if abs(following) >= abs(term):
            break
        total += following
        if abs(following) <= 2e-16 * abs(total):
            break
        term = following
    return total


def _mills_difference(start, delta):
    """M(start)-M(start+delta), start>=0, with delta retained separately."""
    if delta == 0:
        return 0.0
    if start >= 24:
        ratio_log = math.log1p(delta / start)
        coefficient = 1 / start
        total = 0.0
        previous = math.inf
        for n in range(100):
            term = coefficient * (-math.expm1(-(2 * n + 1) * ratio_log))
            if abs(term) >= previous:
                break
            total += term
            if abs(term) <= 2e-16 * abs(total):
                break
            previous = abs(term)
            coefficient *= -(2 * n + 1) / (start * start)
        return total
    first = _mills(start)
    difference = first - _mills(start + delta)
    if difference > 1e-5 * first:
        return difference
    # Positive, scaled integral; no subtraction and no tiny absolute integrand.
    scale = max(1.0, start)

    def integrand(z):
        w = delta * z / scale
        relative = -math.expm1(-w) / w if w else 1.0
        return z * math.exp(-start * z / scale - z * z / (2 * scale * scale)) * relative

    integral = quad(integrand, 0, math.inf, epsabs=2e-12, epsrel=2e-12)[0]
    return delta * integral / (scale * scale)


def _positive_log_survival_uv(u, distance_scaled, drift_scaled):
    log_phi = -0.5 * u * u - LOG_SQRT_2PI
    if u < 0:
        difference = _mills_difference(-u, 2 * distance_scaled)
        return log_phi + math.log(difference)
    difference = _mills_difference(u, 2 * drift_scaled)
    erf_part = math.erf(u / math.sqrt(2))
    log_first = math.log(erf_part) if erf_part else -math.inf
    log_second = log_phi + math.log(difference) if difference else -math.inf
    return min(0.0, float(np.logaddexp(log_first, log_second)))


def _positive_log_survival(distance, time, mu, sigma):
    scale = sigma * math.sqrt(time)
    return _positive_log_survival_uv((distance-mu*time)/scale,
                                     distance/scale, mu*math.sqrt(time)/sigma)


def _positive_log_cdf_uv(u, v, distance_scaled, drift_scaled):
    log_mirror = -0.5 * u * u - LOG_SQRT_2PI + math.log(_mills(v))
    value = float(np.logaddexp(log_ndtr(-u), log_mirror))
    if value > -math.log(2):
        value = _log1mexp(_positive_log_survival_uv(u, distance_scaled, drift_scaled))
    return value


def log_fpt_cdf(distance, time, mu, sigma):
    _validate(distance, time, mu, sigma)
    if distance == 0:
        return 0.0
    if time == 0:
        return -math.inf
    positive_mu = abs(mu)
    scale = sigma * math.sqrt(time)
    u = (distance - positive_mu * time) / scale
    v = (distance + positive_mu * time) / scale
    value = _positive_log_cdf_uv(u, v, distance/scale, positive_mu*math.sqrt(time)/sigma)
    if mu < 0:
        value += 2 * mu * distance / (sigma * sigma)
    return value


def log_survival(distance, time, mu, sigma):
    _validate(distance, time, mu, sigma)
    if distance == 0:
        return -math.inf
    if time == 0:
        return 0.0
    if mu >= 0:
        return _positive_log_survival(distance, time, mu, sigma)
    return _log1mexp(log_fpt_cdf(distance, time, mu, sigma))


def _kappa_beta(mu, sigma, rate):
    kappa = math.hypot(mu, sigma * math.sqrt(2 * rate))
    beta = 2 * rate / (kappa + mu) if mu >= 0 and kappa else (kappa - mu) / sigma**2
    return kappa, beta


def _tilted_arguments(distance, time, mu, sigma, rate):
    """Keep kappa-|mu| below one ULP: its standardized shift can be material."""
    kappa, beta = _kappa_beta(mu, sigma, rate)
    scale, absolute_mu = sigma * math.sqrt(time), abs(mu)
    shift = 2*rate*sigma*math.sqrt(time)/(kappa+absolute_mu) if kappa else 0.0
    u = (distance-absolute_mu*time)/scale - shift
    v = (distance+absolute_mu*time)/scale + shift
    drift_scaled = absolute_mu*math.sqrt(time)/sigma + shift
    return kappa, beta, u, v, distance/scale, drift_scaled


def log_discounted_hit(distance, time, mu, sigma, rate):
    _validate(distance, time, mu, sigma)
    if not math.isfinite(rate) or rate < 0:
        raise ValueError("nonnegative finite rate required")
    if distance == 0:
        return 0.0
    if time == 0:
        return -math.inf
    if rate == 0:
        return log_fpt_cdf(distance, time, mu, sigma)
    _, beta, u, v, ds, ms = _tilted_arguments(distance, time, mu, sigma, rate)
    return -beta * distance + _positive_log_cdf_uv(u, v, ds, ms)


def log_no_hit(distance, time, mu, sigma, rate):
    """Marginalize hidden cancellation without subtracting H from one."""
    _validate(distance, time, mu, sigma)
    if not math.isfinite(rate) or rate < 0:
        raise ValueError("nonnegative finite rate required")
    if distance == 0:
        return -math.inf
    if time == 0:
        return 0.0
    if rate == 0:
        return log_survival(distance, time, mu, sigma)
    _, beta, u, _, ds, ms = _tilted_arguments(distance, time, mu, sigma, rate)
    exponent = -beta*distance
    return float(np.logaddexp(_log1mexp(exponent),
                             exponent+_positive_log_survival_uv(u, ds, ms)))


def log_fpt_density(distance, time, mu, sigma):
    _validate(distance, time, mu, sigma)
    if distance == 0 or time == 0:
        return -math.inf
    return (math.log(distance / sigma) - LOG_SQRT_2PI - 1.5 * math.log(time)
            - (distance - mu * time)**2 / (2 * sigma**2 * time))


def cdf_derivatives(distance, time, mu, sigma):
    _validate(distance, time, mu, sigma)
    if not distance or not time:
        raise ValueError("CDF derivative requires the active interior")
    scale = sigma * math.sqrt(time)
    u, v = (distance - mu * time) / scale, (distance + mu * time) / scale
    phi = math.exp(-0.5 * u * u - LOG_SQRT_2PI)
    if v >= 0:
        mills = _mills(v)
        complement = _mills_complement(v)
        mirror = phi * mills
        d_distance = -2 * phi / scale * (complement + distance / scale * mills)
        d_sigma = 2 * distance * phi / (sigma * scale) * (complement + u * mills)
    else:
        mirror = math.exp(2 * mu * distance / sigma**2 + float(log_ndtr(-v)))
        d_distance = -2 * phi / scale + 2 * mu * mirror / sigma**2
        d_sigma = 2 * distance * phi / (sigma * scale) - 4 * mu * distance * mirror / sigma**3
    return np.array([d_distance, 2 * distance * mirror / sigma**2,
                     d_sigma, math.exp(log_fpt_density(distance, time, mu, sigma))])


def _survival_score(distance, time, mu, sigma):
    scale = sigma * math.sqrt(time)
    u, v = (distance - mu * time) / scale, (distance + mu * time) / scale
    if mu >= 0 and u < 0:
        difference = _mills_difference(-u, 2 * distance / scale)
        phi_ratio = 1 / difference
        mirror_ratio = _mills(v) / difference
    else:
        logs = log_survival(distance, time, mu, sigma)
        phi_ratio = math.exp(-0.5 * u * u - LOG_SQRT_2PI - logs)
        mirror_ratio = (phi_ratio * _mills(v) if v >= 0 else
                        math.exp(2 * mu * distance / sigma**2 + float(log_ndtr(-v)) - logs))
    d_mu = -2 * distance * mirror_ratio / sigma**2
    if v >= 0:
        d_sigma = -2 * distance * phi_ratio / (sigma * scale) * (_mills_complement(v) + u * _mills(v))
    else:
        d_sigma = -2 * distance * phi_ratio / (sigma * scale) + 4 * mu * distance * mirror_ratio / sigma**3
    return np.array([d_mu, d_sigma])


def discounted_hit_derivatives(distance, time, params):
    """Absolute H derivatives in mu, sigma, cancellation; finite-time limits."""
    params.validate()
    _validate(distance, time, params.mu, params.sigma)
    if not distance or not time:
        return np.zeros(3)
    mu, sigma, rate = params.mu, params.sigma, params.cancel_rate
    kappa, beta, u, v, _, drift_scaled = _tilted_arguments(distance,time,mu,sigma,rate)
    if kappa == 0:
        z = distance / (sigma * math.sqrt(time))
        truncated_time = (2 * distance * math.sqrt(time) / sigma
                          * math.exp(-z*z/2 - LOG_SQRT_2PI) * _mills_complement(z))
        derivative = cdf_derivatives(distance, time, mu, sigma)
        return np.array([derivative[1], derivative[2], -truncated_time])
    prefactor = math.exp(-beta * distance)
    h = math.exp(log_discounted_hit(distance, time, mu, sigma, rate))
    scale = sigma * math.sqrt(time)
    phi = math.exp(-u*u/2 - LOG_SQRT_2PI)
    mirror = phi * _mills(v)
    if u >= 0:
        difference = phi * _mills_difference(u, 2*drift_scaled)
    else:
        difference = float(np.exp(log_ndtr(-u))) - mirror
    first_moment = prefactor * distance / kappa * difference
    d_mu = (h * distance * beta / kappa + prefactor * 2*mu*distance*mirror/(kappa*sigma**2)
            if mu >= 0 else (distance*h-mu*first_moment)/sigma**2)
    f_mu = 2*distance*mirror/sigma**2
    f_sigma = 2*distance*phi/(sigma*scale)*(_mills_complement(v)+u*_mills(v))
    d_sigma = (h * distance * sigma * beta**2/kappa + prefactor
               * (f_sigma + f_mu*2*rate*sigma/kappa))
    return np.array([d_mu, d_sigma, -first_moment])


def log_event_likelihood(event, time, distance, params):
    params.validate()
    _validate(distance, time, params.mu, params.sigma)
    if event not in {"hit", "cancel", "survive", "no_hit"}:
        raise ValueError("unknown observation event")
    if distance == 0:
        return 0.0 if event == "hit" and time == 0 else -math.inf
    if event == "hit":
        return log_fpt_density(distance, time, params.mu, params.sigma) - params.cancel_rate*time
    if event == "no_hit":
        return log_no_hit(distance,time,params.mu,params.sigma,params.cancel_rate)
    value = log_survival(distance, time, params.mu, params.sigma) - params.cancel_rate*time
    if event == "cancel":
        return value + math.log(params.cancel_rate) if params.cancel_rate else -math.inf
    return value


def score_event(event, time, distance, params):
    logp = log_event_likelihood(event, time, distance, params)
    if not math.isfinite(logp):
        raise ValueError("score of an impossible observation is undefined")
    if distance == 0:
        return np.zeros(3)
    if event == "hit":
        residual = distance - params.mu*time
        return np.array([residual/params.sigma**2,
                         -1/params.sigma+residual**2/(params.sigma**3*time), -time])
    if event == "no_hit":
        return -discounted_hit_derivatives(distance,time,params) * math.exp(-logp)
    pair = _survival_score(distance,time,params.mu,params.sigma) if time else np.zeros(2)
    return np.array([pair[0],pair[1], -time+(1/params.cancel_rate if event == "cancel" else 0)])


def outcome_law(distance, horizon, params):
    params.validate()
    _validate(distance,horizon,params.mu,params.sigma)
    if distance == 0:
        return np.array([1.0,0.0,0.0])
    if horizon == 0:
        return np.array([0.0,1.0,0.0])
    hit = math.exp(log_discounted_hit(distance,horizon,params.mu,params.sigma,params.cancel_rate))
    log_alive = log_survival(distance,horizon,params.mu,params.sigma)-params.cancel_rate*horizon
    survival = math.exp(log_alive)
    if params.cancel_rate == 0:
        cancel = 0.0
    elif params.cancel_rate*horizon < 1e-8:
        # 0 <= lambda E[min(tau,T)]-C <= lambda*T/2 times its leading term.
        un_killed = Params(params.mu,params.sigma,0.0)
        mean_capped_time = (-discounted_hit_derivatives(distance,horizon,un_killed)[2]
                           +horizon*math.exp(log_survival(distance,horizon,params.mu,params.sigma)))
        cancel = params.cancel_rate*mean_capped_time
    else:
        log_no_event = log_no_hit(distance,horizon,params.mu,params.sigma,params.cancel_rate)
        cancel = math.exp(log_no_event)*(-math.expm1(log_alive-log_no_event))
    probabilities = np.array([hit,survival,cancel])
    if np.min(probabilities)<0 or abs(float(probabilities.sum())-1)>2e-10:
        raise ArithmeticError("competing-event probability mass failed")
    return probabilities
