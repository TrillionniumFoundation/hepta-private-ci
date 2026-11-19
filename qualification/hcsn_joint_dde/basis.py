"""Same-law value integrals, with spatial and upper-truncation errors separate.

The original source coefficients describe uniform densities, an exponential
tail and uniform remaining delay. These routines integrate each model's
continuation on those exact laws; they do not collapse a cell to its centre.
They are value quadrature, not an initial-law rollout migration certificate.
"""

import math

import numpy as np
from scipy.integrate import quad

from qualification.hcsn_boundary_audit.spatial_generator import continuum_lower_hit


def _uniform_linear(nodes, values, left, right):
    points = np.r_[left, nodes[(nodes > left) & (nodes < right)], right]
    heights = np.interp(points, nodes, values)
    return float(
        np.sum(np.diff(points) * (heights[:-1] + heights[1:]) / 2) / (right - left)
    )


def _tail_linear(nodes, values, endpoint, rate):
    points = np.r_[endpoint, nodes[nodes > endpoint]]
    heights = np.interp(points, nodes, values)
    result = 0.0
    for left, right, lo, hi in zip(points[:-1], points[1:], heights[:-1], heights[1:]):
        width = right - left
        decay = math.exp(-rate * width)
        zeroth = -math.expm1(-rate * width)
        first = zeroth / rate - width * decay
        result += math.exp(-rate * (left - endpoint)) * (
            lo * zeroth + (hi - lo) / width * first
        )
    return result + values[-1] * math.exp(-rate * (nodes[-1] - endpoint))


def basis_values(
    model, *, original_endpoint=4.8, active_cells=16, phase_cells=8, tail_rate=1.0
):
    """Candidate, finite-continuum and half-line values on identical basis laws.

    Candidate upper escape remains permanently active. The finite-continuum
    comparison has the same upper semantics; the half-line reference returns
    from its tail. No tail/spatial cancellation is treated as qualification.
    """
    if (
        not 0 < original_endpoint <= model.spatial.endpoint
        or type(active_cells) is not int
        or not 1 <= active_cells <= 256
        or type(phase_cells) is not int
        or not 1 <= phase_cells <= 128
        or not math.isfinite(tail_rate)
        or tail_rate <= 0
    ):
        raise ValueError("invalid original reconstruction basis")
    mu, sigma, q, delay = (
        model.spatial.mu,
        model.spatial.sigma,
        model.discount,
        model.delay,
    )
    a, h = model.active_reward, model.hit_reward
    alpha = 2 * q / (math.hypot(mu, math.sqrt(2 * q) * sigma) - mu)
    eta, baseline = math.exp(-q * delay), a / q
    phi_r_inf = math.exp(-alpha * model.reset)
    phi_r_finite = float(
        continuum_lower_hit([model.reset], model.spatial.endpoint, mu, sigma, q)[0]
    )

    def closure(phi_r):
        reset_value = (baseline * (1 - phi_r) + h * phi_r) / (1 - eta * phi_r)
        return reset_value, h + eta * reset_value - baseline

    inf_reset, inf_coefficient = closure(phi_r_inf)
    finite_reset, finite_coefficient = closure(phi_r_finite)
    candidate_nodes, candidate_reset = model.perpetual()
    nodes = model.spatial.nodes
    edges = np.linspace(0, original_endpoint, active_cells + 1)
    candidate, finite, infinite = [], [], []
    for left, right in zip(edges[:-1], edges[1:]):
        candidate.append(_uniform_linear(nodes, candidate_nodes, left, right))
        average_finite = quad(
            lambda x: float(
                continuum_lower_hit([x], model.spatial.endpoint, mu, sigma, q)[0]
            ),
            left,
            right,
            epsabs=2e-13,
            epsrel=2e-13,
        )[0] / (right - left)
        average_infinite = (
            math.exp(-alpha * left)
            * -math.expm1(-alpha * (right - left))
            / (alpha * (right - left))
        )
        finite.append(baseline + finite_coefficient * average_finite)
        infinite.append(baseline + inf_coefficient * average_infinite)
    candidate.append(_tail_linear(nodes, candidate_nodes, original_endpoint, tail_rate))
    average_finite_tail = quad(
        lambda x: (
            tail_rate
            * math.exp(-tail_rate * (x - original_endpoint))
            * float(continuum_lower_hit([x], model.spatial.endpoint, mu, sigma, q)[0])
        ),
        original_endpoint,
        model.spatial.endpoint,
        epsabs=2e-13,
        epsrel=2e-13,
    )[0]
    finite.append(baseline + finite_coefficient * average_finite_tail)
    infinite.append(
        baseline
        + inf_coefficient
        * math.exp(-alpha * original_endpoint)
        * tail_rate
        / (tail_rate + alpha)
    )
    phase_edges = np.linspace(0, delay, phase_cells + 1)
    for left, right in zip(phase_edges[:-1], phase_edges[1:]):
        discount_average = (
            math.exp(-q * left)
            * -math.expm1(-q * (right - left))
            / (q * (right - left))
        )
        candidate.append(candidate_reset * discount_average)
        finite.append(finite_reset * discount_average)
        infinite.append(inf_reset * discount_average)
    return {
        "candidate": np.asarray(candidate),
        "finite_continuum": np.asarray(finite),
        "halfline_continuum": np.asarray(infinite),
        "spatial_reset_basis_error": np.asarray(candidate) - finite,
        "upper_truncation_error": np.asarray(finite) - infinite,
    }
