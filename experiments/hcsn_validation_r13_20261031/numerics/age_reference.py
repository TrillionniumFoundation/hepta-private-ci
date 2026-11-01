"""Continuous refractory-age functionals independent of the forward solver."""

import math

import numpy as np
from scipy.integrate import quad

from experiments.hcsn_validation_r12_20261031.numerics import dynamics


def recovery_reference(case, age_edges, active_edges):
    x, mu, sigma, horizon, reset, delay = [case[key] for key in
        ("x", "mu", "sigma", "horizon", "reset", "refractory")]

    def density(age):
        answer = 0.0
        for n in range(1, math.ceil(horizon / delay) + 1):
            waiting_time = horizon - (n - 1) * delay - age
            distance = x + (n - 1) * reset
            if waiting_time > 0:
                answer += distance * math.exp(-(distance + mu * waiting_time)**2
                    / (2 * sigma**2 * waiting_time)) / (
                    sigma * math.sqrt(2 * math.pi) * waiting_time**1.5)
        return answer

    moments = [quad(lambda age: age**power * density(age), 0, delay,
                    epsabs=2e-12, epsrel=2e-11) for power in range(3)]
    bins = [quad(density, lo, hi, epsabs=2e-12, epsrel=2e-11)
            for lo, hi in zip(age_edges[:-1], age_edges[1:])]
    upstream = dynamics.regenerative_successor(case, active_edges)
    return {
        "age_moments": [value for value, error in moments],
        "age_bins": [value for value, error in bins],
        "quadrature_error_estimates": [error for value, error in moments + bins],
        "upstream_recovery_moments": upstream["recovery"],
        "upstream_moment_difference": (np.asarray([v for v, _ in moments])
                                       - np.asarray(upstream["recovery"])).tolist(),
        "active_moments": upstream["active"][:3],
        "active_bins": upstream["active"][3:],
        "event_count": upstream["expected_count"],
        "continuous_mass": upstream["mass"],
        "reference_scope": "Continuous constant-coefficient fixed-reset renewal; independent of age queue and forward-grid rates",
    }
