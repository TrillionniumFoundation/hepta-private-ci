"""Values of the declared projected chain, separate from continuum renewal U.

The existing ``call`` is a one-interval feature that includes terminal reward.
Only running and event rewards enter a Bellman continuation. These functions
evaluate a fixed, unconditioned law: observation filtering is not applied.
"""

from dataclasses import dataclass

import torch

from .operator import _check_parameters, _finite


@dataclass(frozen=True)
class BasisValue:
    """A value per represented starting density, with a residual-based error estimate."""

    value: torch.Tensor
    interval_reward: torch.Tensor
    bellman_residual: torch.Tensor
    residual_error_estimate: torch.Tensor
    contraction_norm: torch.Tensor


def _table_and_reward(operator, params, duration):
    table = operator(params.log_boundary, params.mu, params.sigma,
                     params.absolute_reset, duration, params.discount)
    reward = (operator.active_reward * table.rewards[:, 2]
              + operator.hit_reward * table.rewards[:, 1])
    return table, reward


def perpetual_basis_value(operator, params, duration):
    """Solve the fixed-step QPR Bellman system, without terminal payments.

    This is U for the *projected* Markov reward chain, not the continuum U.
    The residual estimate uses a rounded residual and norm; it is not a
    certified floating-point bound. It does not cover
    quadrature, spatial/tail reconstruction, phase projection or time stepping.
    """
    _check_parameters(params)
    table, reward = _table_and_reward(operator, params, duration)
    if table.duration <= 0:
        raise ValueError("perpetual continuation requires positive duration")
    discounted = torch.exp(-params.discount * table.duration) * table.matrix
    norm = discounted.abs().sum(-1).max()
    if not bool(norm < 1):
        raise FloatingPointError("projected continuation is not a contraction")
    system = torch.eye(operator.state_count, dtype=reward.dtype,
                       device=reward.device) - discounted
    value = torch.linalg.solve(system, reward)
    residual = value - reward - discounted @ value
    bound = residual.abs().max() / (1 - norm)
    _finite("projected perpetual value", value)
    _finite("Bellman residual estimate", bound)
    return BasisValue(value, reward, residual, bound, norm)


def finite_basis_value(operator, params, durations):
    """Backward value with one terminal active payoff at the final horizon.

    Durations are fixed data, each in [0, refractory]. Empty schedules and
    zero-length steps pay the terminal payoff once; padding does not add value.
    Running/event rewards are discounted from their own interval starts.
    """
    _check_parameters(params)
    durations = tuple(durations)
    active = params.mu.new_zeros(operator.state_count)
    active[:operator.grid.active_count] = operator.terminal_reward
    value = active
    for duration in reversed(durations):
        table, reward = _table_and_reward(operator, params, duration)
        value = reward + torch.exp(-params.discount * table.duration) * (table.matrix @ value)
    _finite("projected finite-horizon value", value)
    return value
