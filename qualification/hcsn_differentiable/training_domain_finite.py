"""Finite continuation of a recorded law under its real gap schedule.

No future observation updates are applied in this shadow comparison. The
reference uses independent 80-digit renewal expressions and positive Gaussian
quadrature. Its order-doubling delta is a measured sensitivity, not a certified
bound. The perpetual constant-minimum-gap pressure test remains separate.
"""

from dataclasses import asdict
import hashlib
import json
import math

import mpmath as mp
import numpy as np
import torch

from .contract import PhysicalParameters
from .operator import DifferentiableDistributionOperator
from .value import finite_basis_value


def _point(x, horizon, values, delay, active_reward, hit_reward, terminal_reward):
    """Return U_T, M_T, discounted M_T, and active probability for x>0."""
    _, mu, sigma, reset, rho = map(mp.mpf, values)
    reset_distance = mp.log(reset) - mp.mpf(values[0])
    horizon, delay, x = map(mp.mpf, (horizon, delay, x))
    if horizon <= 0:
        return [mp.mpf(terminal_reward), mp.mpf(0), mp.mpf(0), mp.mpf(1)]
    root = mp.sqrt(mu * mu + 2 * rho * sigma * sigma)

    def hit(distance, time, discount):
        if time <= 0:
            return mp.mpf(0)
        drift = root if discount else mu
        scale = sigma * mp.sqrt(time)
        left = mp.erfc((distance + drift * time) / scale / mp.sqrt(2)) / 2
        right = mp.erfc((distance - drift * time) / scale / mp.sqrt(2)) / 2
        if discount:
            return (
                mp.exp((root - mu) * distance / sigma**2) * left
                + mp.exp(-(root + mu) * distance / sigma**2) * right
            )
        return left + mp.exp(-2 * mu * distance / sigma**2) * right

    count = int(mp.floor(horizon / delay)) + 1
    events = discounted = recent = recent_discounted = previous_discounted = mp.mpf(0)
    for k in range(count):
        time, distance = horizon - k * delay, x + k * reset_distance
        f, old_f = hit(distance, time, False), hit(distance, time - delay, False)
        g, old_g = hit(distance, time, True), hit(distance, time - delay, True)
        weight = mp.exp(-rho * k * delay)
        events += f
        discounted += weight * g
        recent += f - old_f
        recent_discounted += weight * (g - old_g)
        previous_discounted += weight * old_g
    endpoint_discount = mp.exp(-rho * horizon)
    refractory = (
        (1 - mp.exp(-rho * delay)) * previous_discounted
        + recent_discounted
        - endpoint_discount * recent
    ) / rho
    active_time = (1 - endpoint_discount) / rho - refractory
    active = 1 - recent
    value = (
        active_reward * active_time
        + hit_reward * discounted
        + terminal_reward * endpoint_discount * active
    )
    return [value, events, discounted, active]


def _reference(probability, grid, values, horizon, operator, order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    nodes, weights = (nodes + 1) / 2, weights / 2
    count_bound = math.floor(horizon / grid.refractory) + 1
    value_bound = (
        operator.active_reward * horizon
        + operator.hit_reward * count_bound
        + operator.terminal_reward
    )
    maximum = max(1.0, count_bound, value_bound)
    result, omitted = [mp.mpf(0)] * 4, mp.mpf(0)
    params = list(map(mp.mpf, values))
    for index, coefficient in enumerate(probability):
        p = mp.mpf(coefficient)
        if p <= mp.mpf("1e-13") / (grid.state_count * maximum):
            omitted += p
            continue
        for node, weight in zip(nodes, weights):
            if index < grid.active_cells:
                x = mp.mpf(grid.active_edges[index]) + mp.mpf(node) * (
                    mp.mpf(grid.active_edges[index + 1])
                    - mp.mpf(grid.active_edges[index])
                )
                quantities = _point(
                    x,
                    horizon,
                    params,
                    grid.refractory,
                    operator.active_reward,
                    operator.hit_reward,
                    operator.terminal_reward,
                )
            elif index == grid.active_cells:
                x = mp.mpf(grid.endpoint) - mp.log(1 - mp.mpf(node)) / grid.tail_rate
                quantities = _point(
                    x,
                    horizon,
                    params,
                    grid.refractory,
                    operator.active_reward,
                    operator.hit_reward,
                    operator.terminal_reward,
                )
            else:
                phase = index - grid.active_count
                left, right = map(mp.mpf, grid.phase_edges[phase : phase + 2])
                right = min(right, mp.mpf(horizon))
                if right <= left:
                    continue
                remaining = left + mp.mpf(node) * (right - left)
                fraction = (right - left) / (mp.mpf(grid.phase_edges[phase + 1]) - left)
                quantities = _point(
                    mp.log(params[3]) - params[0],
                    mp.mpf(horizon) - remaining,
                    params,
                    grid.refractory,
                    operator.active_reward,
                    operator.hit_reward,
                    operator.terminal_reward,
                )
                factor = mp.exp(-params[4] * remaining)
                quantities = [
                    quantities[0] * factor,
                    quantities[1],
                    quantities[2] * factor,
                    quantities[3],
                ]
                weight = mp.mpf(weight) * fraction
            result = [
                total + p * mp.mpf(weight) * q for total, q in zip(result, quantities)
            ]
    return np.array([float(v) for v in result]), float(omitted * maximum)


def audit_finite_schedule(
    probability, grid, params, durations, *, reference_order=16, operator=None
):
    durations = tuple(float(d) for d in durations)
    if (
        not durations
        or len(durations) > 4096
        or any(not math.isfinite(d) or d < 0 or d > grid.refractory for d in durations)
        or reference_order not in (8, 16, 32, 64)
    ):
        raise ValueError(
            "bounded valid fixed gap schedule and declared quadrature order required"
        )
    if (
        probability.shape != (grid.state_count,)
        or probability.dtype != torch.float64
        or probability.device.type != "cpu"
        or not bool(torch.isfinite(probability).all())
        or bool((probability < 0).any())
        or abs(float(probability.sum()) - 1) > 5e-11
    ):
        raise ValueError("a normalized nonnegative CPU FP64 recorded law is required")
    values = [float(v.detach()) for v in params.tensors()]
    params = PhysicalParameters(*(torch.tensor(v, dtype=torch.float64) for v in values))
    operator = (
        DifferentiableDistributionOperator(grid) if operator is None else operator
    )
    if (
        not isinstance(operator, DifferentiableDistributionOperator)
        or operator.grid != grid
        or not operator.reset_enabled
    ):
        raise ValueError(
            "the finite renewal oracle requires a matching regenerative operator"
        )
    # Retain the full tested law and schedule: a total horizon alone cannot
    # identify repeated QPR projections, and other reward configurations differ.
    inputs = {
        "probability": probability.detach().tolist(),
        "dtype": "float64",
        "device": "cpu",
        "grid": asdict(grid),
        "operator": operator.configuration(),
        "parameters": dict(
            zip(("log_boundary", "mu", "sigma", "absolute_reset", "discount"), values)
        ),
        "durations": list(durations),
    }
    input_digest = hashlib.sha256(
        json.dumps(
            inputs, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    with torch.no_grad():
        value = float(probability @ finite_basis_value(operator, params, durations))
        current, events, discounted, elapsed, residual = probability, 0.0, 0.0, 0.0, 0.0
        for dt in durations:
            table = operator(*params.tensors()[:4], dt, params.discount)
            events += float(current @ table.rewards[:, 0])
            discounted += math.exp(-values[-1] * elapsed) * float(
                current @ table.rewards[:, 1]
            )
            current = current @ table.matrix
            residual = max(residual, abs(float(current.sum()) - 1))
            elapsed += dt
        actual = np.array(
            [value, events, discounted, float(current[: grid.active_count].sum())]
        )
    with mp.workdps(80):
        first, omitted = _reference(
            probability.tolist(),
            grid,
            values,
            math.fsum(durations),
            operator,
            reference_order,
        )
        refined, omitted_refined = _reference(
            probability.tolist(),
            grid,
            values,
            math.fsum(durations),
            operator,
            2 * reference_order,
        )
    scale = np.maximum(1.0, np.abs(refined))
    sensitivity = float(np.max(np.abs(first - refined) / scale))
    error = np.abs(actual - refined) / scale
    return {
        "schema": "hcsn-recorded-law-finite-continuation-v1",
        "quantities": [
            "value",
            "event_count",
            "discounted_event_count",
            "active_probability",
        ],
        "inputs": inputs,
        "inputs_sha256": input_digest,
        "projected": actual.tolist(),
        "reference": refined.tolist(),
        "scaled_errors": error.tolist(),
        "horizon": math.fsum(durations),
        "intervals": len(durations),
        "minimum_dt": min(durations),
        "maximum_dt": max(durations),
        "mass_residual": residual,
        "reference_digits": 80,
        "reference_orders": [reference_order, 2 * reference_order],
        "reference_refinement_delta": sensitivity,
        "reference_omission_bound": max(omitted, omitted_refined),
        "scaled_error_limit": 0.01,
        "status": "passed_fixture"
        if max(error) <= 0.01 and sensitivity <= 2e-8 and residual <= 5e-11
        else "HOLD",
        "scope": "Fixed recorded starting law; actual gap schedule; future observations disabled; no whole-training admission.",
    }
