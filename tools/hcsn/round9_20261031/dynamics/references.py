"""Independent continuous density integrals for the registered repair fixtures.

These references do not import the tested event kernel. Quadrature estimates
exclude roundoff; the explicit Gaussian tail bounds cover integration cutoffs.
"""

import math

import numpy as np
from scipy.integrate import quad
from scipy.special import erfcx, gammainc, gammaln, ndtr


def second_maximum_reference(crossing_z, duration):
    """First leg d=1, mu=0, sigma=.5, t=1; second positive drift, sigma=.5.

    Exchange the order of integration: average the first killed-endpoint CDF
    over the second Brownian maximum density, in the latter's own scale.
    """
    scale = .5 * math.sqrt(duration)
    crossing = 1. + .5 * crossing_z
    v = crossing / scale

    def integrand(z):
        maximum = crossing + scale * z
        if maximum <= 0:
            return 0.
        killed_cdf = (float(ndtr((maximum - 1.) / .5)) - float(ndtr(-2.))
                      - float(ndtr((maximum + 1.) / .5)) + float(ndtr(2.)))
        mills = math.sqrt(math.pi / 2) * float(erfcx((2 * v + z) / math.sqrt(2)))
        density = math.exp(-.5 * z * z) / math.sqrt(2 * math.pi) * (2 - 2 * v * mills)
        return killed_cdf * density

    value, error = quad(integrand, max(-v, -12.), 12., points=[-8., -4., 0., 4., 8.],
                        epsabs=2e-14, epsrel=2e-13, limit=200)
    return dict(probability=2 * float(ndtr(-2.)) + value,
                quadrature_error_estimate=error,
                omitted_mass_upper_bound=4 * float(ndtr(-12.)),
                step_limit=float(ndtr(crossing_z) + ndtr(-crossing_z - 4.)))


def log_time_count(initial_gap, reset_gap, drift, sigma, time, recovery_mean,
                   phases=2, terms=24):
    """Positive-drift renewal count via a log-time inverse-Gaussian integral.

    For gap d, t=(d/mu)*exp(beta*z), beta=sigma/sqrt(mu*d).
    The transformed density is exp(-beta*z/2 -
    (2*sinh(beta*z/2)/beta)^2/2)/sqrt(2*pi). This differs from the
    tested normal first-passage coordinate, including its analytic derivatives.
    """
    if drift <= 0:
        raise ValueError("Registered reference requires positive drift")
    rows, error, cutoff_bound = [], 0., 0.
    rate = phases / recovery_mean
    for event in range(1, terms + 1):
        gap = initial_gap + (event - 1) * reset_gap
        beta = sigma / math.sqrt(drift * gap)
        center = gap / drift
        upper = min(16., math.log(time / center) / beta)
        cutoff_bound += math.exp(beta * beta / 8) * float(
            ndtr(-16. + beta / 2) + ndtr(-16. - beta / 2))
        if upper <= -16.:
            rows.append(0.)
            continue

        def integrand(z):
            active_time = center * math.exp(beta * z)
            recovery = max(0., time - active_time)
            density = math.exp(-.5 * beta * z - .5 * (2 * math.sinh(.5 * beta * z) / beta)**2)
            probability = 1. if event == 1 else float(gammainc(phases * (event - 1), rate * recovery))
            return density * probability / math.sqrt(2 * math.pi)

        points = [z for z in (-8., -4., 0., 4., 8.) if -16. < z < upper]
        value, estimate = quad(integrand, -16., upper, points=points,
                               epsabs=2e-14, epsrel=2e-13, limit=200)
        rows.append(value)
        error += estimate
    return dict(expected_count=sum(rows), event_survival=rows,
                quadrature_error_estimate=error, integration_cutoff_bound=cutoff_bound,
                included_events=terms, event_tail_included=False)


def deterministic_count(initial_gap, reset_gap, drift, time, recovery_mean, phases=2):
    """Zero-noise limiting count and its smooth parameters, away from atoms."""
    total = np.array([float(time > initial_gap / drift), 0., 0., 0., 0., 0.])
    for event in range(2, 513):
        gap = initial_gap + (event - 1) * reset_gap
        recovery = time - gap / drift
        if recovery <= 0:
            break
        shape, rate = phases * (event - 1), phases / recovery_mean
        x = rate * recovery
        pdf = math.exp((shape - 1) * math.log(x) - x - float(gammaln(shape)))
        gap_gradient = -rate * pdf / drift
        total += np.array([float(gammainc(shape, x)), gap_gradient,
                           (event - 1) * gap_gradient, rate * pdf * gap / drift**2,
                           0., -x * pdf / recovery_mean])
    names = ("initial_gap", "reset_gap", "drift", "sigma", "recovery_mean")
    return dict(expected_count=float(total[0]), gradient=dict(zip(names, total[1:].tolist())))
