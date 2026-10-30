"""Independent half-line Brownian renewal statistics, with no spatial grid.

Safety distance X has dX=nu*dt+sigma*dW, absorption at zero, a fixed
positive reset distance, and independent waiting after every absorption.
This evaluates a constant-coefficient process, not a trained recurrent layer.
"""

import math

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import gammaln, log_ndtr


GRADIENT_ORDER = ("nu", "sigma", "initial", "reset", "refractory_mean")


def hit_cdf_gradient(distance, duration, nu, sigma):
    """Return CDF and derivatives in (nu, sigma, distance), plus time density."""
    if distance <= 0 or sigma <= 0:
        raise ValueError("Positive distance and noise required")
    if duration <= 0:
        return 0.0, np.zeros(3), 0.0
    scale = sigma * math.sqrt(duration)
    a, b = (-distance - nu * duration) / scale, (-distance + nu * duration) / scale
    log_image = -2 * nu * distance / sigma**2 + log_ndtr(b)
    image = math.exp(log_image)
    value = math.exp(min(float(np.logaddexp(log_ndtr(a), log_image)), 0.0))
    phi = math.exp(-a * a / 2) / math.sqrt(2 * math.pi)
    gradient = np.array([
        -2 * distance * image / sigma**2,
        2 * distance * phi / (sigma**2 * math.sqrt(duration))
        + 4 * nu * distance * image / sigma**3,
        -2 * phi / scale - 2 * nu * image / sigma**2,
    ])
    density = distance * phi / (sigma * duration**1.5)
    return value, gradient, density


def hit_after_wait(distance, duration, nu, sigma, waits, mean, law, stages):
    """CDF after 'waits' independent waits; final derivative is w.r.t. mean.

    Erlang convolution uses adaptive one-dimensional quadrature. Its local
    quadrature error estimate is returned; it is not a rigorous interval bound.
    """
    if waits == 0 or mean == 0:
        value, gradient, density = hit_cdf_gradient(distance, duration, nu, sigma)
        return np.r_[value, gradient, -waits * density], 0.0
    if law == "deterministic":
        value, gradient, density = hit_cdf_gradient(
            distance, duration - waits * mean, nu, sigma)
        return np.r_[value, gradient, -waits * density], 0.0
    if law != "erlang" or stages < 1:
        raise ValueError("Choose deterministic or positive-stage Erlang waiting")
    shape, rate = waits * stages, stages / mean

    def integrand(wait):
        if wait <= 0 or wait >= duration:
            return np.zeros(5)
        log_pdf = shape * math.log(rate) + (shape - 1) * math.log(wait)
        pdf = math.exp(log_pdf - rate * wait - gammaln(shape))
        value, gradient, _ = hit_cdf_gradient(distance, duration - wait, nu, sigma)
        mean_derivative = value * (-shape / mean + stages * wait / mean**2)
        return np.r_[value, gradient, mean_derivative] * pdf

    value, error = quad_vec(integrand, 0.0, duration, epsabs=2e-12, epsrel=2e-11)
    return value, float(error)


def renewal_statistics(initial, reset, nu, sigma, refractory_mean, duration,
                       law="erlang", stages=2, terms=40):
    """Count, active/refractory inventory, and an analytic-integral count gradient.

    The kth emission time is a Brownian first-passage time across
    initial+(k-1)*reset plus k-1 independent waits. Strong Markov additivity
    makes this a continuous-process reference independent of matrix exponents.
    Gradients differentiate the stated, fixed-number-of-terms expression.
    """
    values = (initial, reset, nu, sigma, refractory_mean, duration)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("Finite scalar parameters required")
    if min(initial, reset, sigma) <= 0 or min(refractory_mean, duration) < 0:
        raise ValueError("Positive distances/noise and nonnegative waiting/time required")
    if terms < 1 or law not in ("erlang", "deterministic") or stages < 1:
        raise ValueError("Invalid waiting law, stages or number of terms")
    counts, refractory, error = 0.0, 0.0, 0.0
    gradient = np.zeros(5)
    emissions = []
    for k in range(1, terms + 1):
        distance = initial + (k - 1) * reset
        enter, err_in = hit_after_wait(distance, duration, nu, sigma, k - 1,
                                      refractory_mean, law, stages)
        leave, err_out = hit_after_wait(distance, duration, nu, sigma, k,
                                       refractory_mean, law, stages)
        counts += enter[0]
        refractory += enter[0] - leave[0]
        gradient += np.array([enter[1], enter[2], enter[3],
                              (k - 1) * enter[3], enter[4]])
        emissions.append(float(enter[0]))
        error += err_in + err_out
    # Markov's inequality applied to exp(-s*T_k), summed geometrically.
    discount = 1.0
    radical = math.sqrt(nu * nu + 2 * sigma**2 * discount)
    exponent = ((radical + nu) / sigma**2 if nu >= 0
                else 2 * discount / (radical - nu))
    log_waiting = (-discount * refractory_mean if law == "deterministic"
                   else -stages * math.log1p(discount * refractory_mean / stages))
    log_ratio = -exponent * reset + log_waiting
    log_tail = discount * duration - exponent * initial
    log_tail += terms * log_ratio - math.log(-math.expm1(log_ratio))
    tail_bound = math.exp(log_tail) if log_tail < 700 else float("inf")
    return dict(expected_events=float(counts), refractory_mass=float(refractory),
                active_mass=float(1 - refractory), count_gradient=gradient.tolist(),
                event_cdfs=emissions, count_tail_bound=float(tail_bound),
                quadrature_error_estimate=float(error), terms=terms,
                scope="Constant-coefficient half-line renewal; no moving boundary or learned policy")
