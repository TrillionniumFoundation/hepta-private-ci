"""Independent 80-digit closed forms on original and migrated initial laws.

Physics/reset and source basis geometry use explicitly declared decimal
round-trip inputs, matching the original reference convention. Uniform source
cells, shifted exponential tail and uniform remaining-time phases are all kept.
"""

from functools import lru_cache

import mpmath as mp
import numpy as np


def _geometry(value):
    return mp.mpf(str(float(value)))


def _exp_average(rate, left, right):
    width = right - left
    return mp.exp(rate * left) * (mp.expm1(rate * width) / (rate * width)
                                 if rate else 1)


@lru_cache(maxsize=16)
def _phis(mu_f, sigma_f, discount_f, endpoint_f, old_endpoint_f,
          active_cells, tail_rate_f, nodes):
    with mp.workdps(80):
        mu, sigma, q = map(_geometry, (mu_f, sigma_f, discount_f))
        endpoint, origin, rate = map(_geometry, (endpoint_f, old_endpoint_f, tail_rate_f))
        kappa = mp.sqrt(mu**2 + 2 * q * sigma**2)
        alpha, beta = 2 * q / (kappa - mu), kappa / sigma**2
        gamma = 2 * beta - alpha
        denominator = -mp.expm1(-2 * beta * endpoint)

        def finite_phi(x):
            return mp.exp(-alpha * x) * -mp.expm1(-2 * beta * (endpoint - x)) / denominator

        half, finite = [], []
        for i in range(active_cells):
            left, right = origin * i / active_cells, origin * (i + 1) / active_cells
            h = _exp_average(-alpha, left, right)
            second = mp.exp(-2 * beta * endpoint) * _exp_average(gamma, left, right)
            half.append(h)
            finite.append((h - second) / denominator)
        width = endpoint - origin
        first = rate * mp.exp(-alpha * origin) * -mp.expm1(-(rate + alpha) * width) / (rate + alpha)
        exponent = gamma - rate
        second = rate * mp.exp(-2 * beta * endpoint + gamma * origin) * (
            mp.expm1(exponent * width) / exponent if exponent else width)
        half.append(mp.exp(-alpha * origin) * rate / (rate + alpha))
        finite.append((first - second) / denominator)
        nodal = tuple(finite_phi(_geometry(x)) for x in nodes)
        return alpha, beta, tuple(half), tuple(finite), nodal


def values(parameters, reset, delay, grid, nodes, active_reward=0.4, hit_reward=1.0):
    with mp.workdps(80):
        q = _geometry(parameters["discount"])
        a, reward = _geometry(active_reward), _geometry(hit_reward)
        endpoint = float(nodes[-1])
        alpha, beta, phi_half, phi_finite, phi_nodes = _phis(
            parameters["mu"], parameters["sigma"], parameters["discount"], endpoint,
            grid["endpoint"], grid["active_cells"], grid["tail_rate"], tuple(nodes))
        xr, physical_delay = _geometry(reset), _geometry(delay)
        baseline, eta = a / q, mp.exp(-q * physical_delay)
        reset_half_phi = mp.exp(-alpha * xr)
        reset_finite_phi = reset_half_phi * -mp.expm1(-2 * beta * (_geometry(endpoint) - xr)) / -mp.expm1(-2 * beta * _geometry(endpoint))

        def closure(phi):
            vr = (baseline * (1 - phi) + reward * phi) / (1 - eta * phi)
            return vr, reward + eta * vr - baseline

        vr_half, coefficient_half = closure(reset_half_phi)
        vr_finite, coefficient_finite = closure(reset_finite_phi)
        half = [baseline + coefficient_half * phi for phi in phi_half]
        finite = [baseline + coefficient_finite * phi for phi in phi_finite]
        phase_factors = []
        for i in range(grid["phase_cells"]):
            left = _geometry(grid["refractory"]) * i / grid["phase_cells"]
            right = _geometry(grid["refractory"]) * (i + 1) / grid["phase_cells"]
            factor = _exp_average(-q, left, right)
            phase_factors.append(factor)
            half.append(vr_half * factor)
            finite.append(vr_finite * factor)
        return {
            "halfline_original": np.asarray(half, dtype=float),
            "finite_original": np.asarray(finite, dtype=float),
            "finite_nodes": np.asarray([baseline + coefficient_finite * phi for phi in phi_nodes], dtype=float),
            "phase_factors": np.asarray(phase_factors, dtype=float),
            "halfline_original_mp80": [mp.nstr(x, 80) for x in half],
            "finite_original_mp80": [mp.nstr(x, 80) for x in finite],
        }
