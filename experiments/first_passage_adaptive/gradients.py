"""True derivatives of a hit/survive/cancel finite-horizon event contract.

The free voltage has constant drift mu and diffusion sigma. Independent physical
cancellation has rate cancel_rate. It competes with first passage and is an
observed outcome, not a discount or an uncharged missing observation.

Values use the closed first-passage law. Jacobians and Hessians differentiate
its density under the integral, avoiding the coalescing-root singularity at
mu=cancel_rate=0. All returned derivatives concern the declared model's
probabilities; they are not a straight-through gradient of a sampled network.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.integrate import quad, quad_vec
from scipy.special import log_ndtr, logsumexp


OUTCOMES = ("hit", "survive", "cancel")
PARAMETER_NAMES = ("distance", "mu", "sigma", "cancel_rate")


@dataclass(frozen=True)
class OutcomeLaw:
    probability: np.ndarray
    jacobian: np.ndarray
    hessian: np.ndarray
    quadrature_error: float


def _log_hit(distance, mu, sigma, rate, horizon):
    d = math.sqrt(mu * mu + 2 * rate * sigma * sigma)
    scale = sigma * math.sqrt(horizon)
    value = float(logsumexp([
        (mu - d) * distance / sigma**2 + log_ndtr((d*horizon-distance)/scale),
        (mu + d) * distance / sigma**2 + log_ndtr((-d*horizon-distance)/scale),
    ]))
    if value > 2e-12:
        raise ArithmeticError("First-passage probability exceeds one")
    return min(0.0, value)


def _survival(distance, mu, sigma, horizon):
    if horizon == 0:
        return 1.0
    scale = sigma * math.sqrt(horizon)
    first = float(log_ndtr((distance-mu*horizon)/scale))
    second = 2*mu*distance/sigma**2 + float(log_ndtr((-distance-mu*horizon)/scale))
    difference = second-first
    if difference >= 0:
        if difference > 2e-12:
            raise ArithmeticError("Invalid survival tail subtraction")
        return 0.0
    return math.exp(first) * (-math.expm1(difference))


def _score_integrals(distance, mu, sigma, rate, horizon, order):
    """Joint undiscounted and competing-hit derivatives; t=T/w^2."""
    size = 5 if order == 1 else 21
    A = distance/(sigma*math.sqrt(horizon))
    B = mu*math.sqrt(horizon)/sigma

    def integrand(w):
        time = horizon/(w*w)
        exponent = -0.5*(A*w-B/w)**2
        if exponent < -730:
            return np.zeros(2*size)
        base = 2*A/math.sqrt(2*math.pi)*math.exp(exponent)
        z = distance-mu*time
        score = np.array([1/distance-z/(sigma*sigma*time), z/sigma**2,
                          -1/sigma+z*z/(sigma**3*time), 0.0])
        score_hit = score.copy()
        score_hit[3] = -time
        plain = np.r_[1.0, score]
        hit = np.r_[1.0, score_hit]
        if order == 2:
            log_hessian = np.zeros((4,4))
            log_hessian[0,0] = -1/distance**2-1/(sigma*sigma*time)
            log_hessian[0,1] = log_hessian[1,0] = 1/sigma**2
            log_hessian[0,2] = log_hessian[2,0] = 2*z/(sigma**3*time)
            log_hessian[1,1] = -time/sigma**2
            log_hessian[1,2] = log_hessian[2,1] = -2*z/sigma**3
            log_hessian[2,2] = 1/sigma**2-3*z*z/(sigma**4*time)
            plain = np.r_[plain, (np.outer(score,score)+log_hessian).ravel()]
            hit = np.r_[hit, (np.outer(score_hit,score_hit)+log_hessian).ravel()]
        return np.r_[base*plain, base*math.exp(-rate*time)*hit]

    values, error = quad_vec(integrand, 1.0, np.inf, epsabs=1e-11,
                             epsrel=2e-11, limit=300)
    if not np.isfinite(values).all() or not np.isfinite(error):
        raise ArithmeticError("Nonfinite first-passage derivative quadrature")
    if error > 1e-8*max(1.0,float(np.max(np.abs(values)))):
        raise ArithmeticError("Derivative quadrature exceeded its numerical error budget")
    return values.reshape(2,size), float(error)


def outcome_law(distance, mu, sigma, cancel_rate, horizon, *, derivatives=2):
    """Return probabilities and derivatives ordered by OUTCOMES/PARAMETER_NAMES.

    An initially active state strictly below the barrier and a positive remaining
    horizon are required. Reset, refractory and already-triggered atoms belong
    to the owner state machine, not to an invented continuation of this kernel.
    derivatives=0 returns zero-filled derivative arrays, not computed gradients.
    """
    values = (distance,mu,sigma,cancel_rate,horizon)
    if (not np.isfinite(values).all() or distance <= 0 or sigma <= 0
            or cancel_rate < 0 or horizon <= 0 or derivatives not in (0,1,2)):
        raise ValueError("Expected finite a>0, sigma>0, lambda>=0, T>0 and order 0/1/2")
    hit = math.exp(_log_hit(distance,mu,sigma,cancel_rate,horizon))
    survival = math.exp(-cancel_rate*horizon)*_survival(distance,mu,sigma,horizon)
    cancellation = 1.0-hit-survival
    if cancel_rate == 0:
        cancellation = 0.0
    elif cancellation < 1e-8:
        cancellation = quad(
            lambda t: cancel_rate*math.exp(-cancel_rate*t)*_survival(distance,mu,sigma,t),
            0,horizon,epsabs=1e-13,epsrel=1e-11,limit=200)[0]
    probability = np.array([hit,survival,cancellation])
    if np.any(probability < 0) or abs(probability.sum()-1.0) > 2e-10:
        raise ArithmeticError("Competing outcomes do not conserve probability")
    jacobian, hessian = np.zeros((3,4)), np.zeros((3,4,4))
    error = 0.0
    if derivatives:
        moments,error = _score_integrals(distance,mu,sigma,cancel_rate,horizon,derivatives)
        plain,competing = moments
        if abs(competing[0]-hit) > max(5e-10,5*error):
            raise ArithmeticError("Closed-form hit law disagrees with density quadrature")
        decay = math.exp(-cancel_rate*horizon)
        jacobian[0] = competing[1:5]
        jacobian[1] = -decay*plain[1:5]
        jacobian[1,3] = -horizon*survival
        jacobian[2] = -jacobian[0]-jacobian[1]
        if derivatives == 2:
            hessian[0] = competing[5:].reshape(4,4)
            hessian[1] = -decay*plain[5:].reshape(4,4)
            hessian[1,:3,3] = -horizon*jacobian[1,:3]
            hessian[1,3,:3] = hessian[1,:3,3]
            hessian[1,3,3] = horizon*horizon*survival
            hessian[2] = -hessian[0]-hessian[1]
    return OutcomeLaw(probability,jacobian,hessian,error)


def expected_task_loss(law, costs):
    """E[loss(hard outcome)], with fixed outcome-conditional costs, and derivatives.

    Costs may include failure, execution, cancellation and terminal costs. A
    caller whose conditional costs depend on parameters must also differentiate
    those costs; this function does not silently assume those derivatives zero.
    """
    costs = np.asarray(costs,dtype=float)
    if costs.shape != (3,) or not np.isfinite(costs).all():
        raise ValueError("Expected three finite outcome-conditional losses")
    return (float(costs@law.probability), costs@law.jacobian,
            np.einsum("i,ijk->jk",costs,law.hessian))
