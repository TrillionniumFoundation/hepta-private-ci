"""Independent zero-drift first implicit-layer oracles, added after a failed gate.

They explain a discretization endpoint, not the true finite-horizon free boundary.
The original experiment remains 91/92. Neither solver nor its gate is changed.
"""

import math

import numpy as np
from scipy.special import lambertw


def continuum_first_layer(spec, dt, states):
    if spec.mu != 0 or not 0 < dt < spec.refractory:
        raise ValueError("this oracle requires zero drift and one step below the lag")
    m = 1 + spec.discount * dt
    kappa = math.sqrt(2 * m / (spec.sigma ** 2 * dt))
    z = 1 + float(lambertw(1 / (math.e * spec.discount * dt)).real)
    boundary = spec.spike_cost + z / kappa
    constant_c = 1 / (2 * m * kappa)
    constant_b = spec.discount * dt * (z + 1) * math.exp(-z) / (2 * m * kappa)
    constant_a = constant_b + constant_c
    x = np.asarray(states, float)
    y = x - spec.spike_cost
    value, first, second = np.empty_like(x), np.empty_like(x), np.empty_like(x)
    below, middle = y < 0, (y >= 0) & (x < boundary)
    stop = x >= boundary
    value[below] = constant_a * np.exp(kappa * y[below])
    first[below], second[below] = kappa * value[below], kappa ** 2 * value[below]
    positive = constant_b * np.exp(kappa * y[middle])
    negative = constant_c * np.exp(-kappa * y[middle])
    value[middle] = y[middle] / m + positive + negative
    first[middle] = 1 / m + kappa * (positive - negative)
    second[middle] = kappa ** 2 * (positive + negative)
    value[stop], first[stop], second[stop] = y[stop], 1.0, 0.0
    return {"boundary": boundary, "value": value, "first": first, "second": second,
            "kappa": kappa, "z": z,
            "root_residual": math.exp(-z) - spec.discount * dt * (z - 1)}


def lattice_first_layer(spec, dt, dx, states):
    if spec.mu != 0 or not 0 < dt < spec.refractory:
        raise ValueError("this oracle requires zero drift and one step below the lag")
    x = np.asarray(states, float)
    coordinates = (x - spec.spike_cost) / dx
    integers = np.rint(coordinates).astype(int)
    if np.max(np.abs(coordinates - integers)) > 5e-8:
        raise ValueError("the strike must lie on the state lattice")
    m, a = 1 + spec.discount * dt, spec.sigma ** 2 * dt / (2 * dx ** 2)
    theta = math.acosh(1 + m / (2 * a))
    rho_minus_one = math.expm1(theta)

    def score(j):
        return spec.discount * dt * (j * rho_minus_one - 1) - math.exp(-j * theta)

    low, high = 0, 1
    while score(high) < 0:
        high *= 2
        if high > 1000000:
            raise ArithmeticError("oracle boundary exceeds the bounded interface")
    while high - low > 1:
        middle = (low + high) // 2
        if score(middle) >= 0:
            high = middle
        else:
            low = middle
    j = high
    constant_c = dx / (m * 2 * math.sinh(theta))
    b_at_j = spec.discount * dt * j * dx / m - constant_c * math.exp(-theta * j)
    constant_a = b_at_j * math.exp(-theta * j) + constant_c
    value = np.maximum(x - spec.spike_cost, 0)
    below, middle = integers < 0, (integers >= 0) & (integers < j)
    value[below] = constant_a * np.exp(theta * integers[below])
    value[middle] = (integers[middle] * dx / m
                    + b_at_j * np.exp(theta * (integers[middle] - j))
                    + constant_c * np.exp(-theta * integers[middle]))
    previous = j - 1
    previous_value = (previous * dx / m + b_at_j * math.exp(-theta)
                      + constant_c * math.exp(-theta * previous))
    wait_gap = previous_value - previous * dx
    stop_residual = a * dx / m * score(j)
    margin = min(wait_gap, stop_residual)
    lower_log_bound = math.log(constant_a) + theta * float(np.min(integers))
    equation = ((m + 2 * a) * value[1:-1] - a * (value[:-2] + value[2:])
                - np.maximum(x[1:-1] - spec.spike_cost, 0))
    gap = value[1:-1] - np.maximum(x[1:-1] - spec.spike_cost, 0)
    residual = max(float(np.max(np.abs(np.minimum(equation, gap)))),
                   float(np.max(np.maximum(-equation, 0))),
                   float(np.max(np.maximum(-gap, 0))))
    return {"boundary": spec.spike_cost + j * dx, "index_from_strike": j,
            "value": value, "theta": theta, "first_stop_score": score(j),
            "previous_continue_score": score(j - 1),
            "complementarity_residual": residual,
            "strict_classification_margin": margin,
            "finite_lower_value_error_log_bound": lower_log_bound,
            "finite_lower_residual_error_log_bound": math.log(m + 4 * a) + lower_log_bound,
            "finite_lower_cannot_change_boundary": margin > 0 and math.log(margin)
            > math.log(m + 4 * a) + lower_log_bound}
