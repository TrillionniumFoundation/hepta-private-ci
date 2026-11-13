"""Closed perpetual values for the declared fixed Brownian/reset policy.

This is a continuum renewal solution, independent of Q P_dt R projection.
The active process has generator mu*d/dx + sigma**2/2*d2/dx2. A first
hit pays ``hit_reward`` once, then waits a fixed ``refractory`` interval
with zero reward before restarting at log(absolute_reset)-log_boundary.
``single_cycle_value`` includes running and hit rewards, but no continuation
or finite-horizon terminal payoff. These values are neither financial equity
E nor an endogenous free-boundary/QVI optimum.
"""

from dataclasses import dataclass
import math

import torch

from .contract import GridSpec
from .operator import _check_parameters, _finite, _tensor


@dataclass(frozen=True)
class PerpetualValue:
    """Distinct first-hit, one-cycle, and repeated-cycle quantities."""

    discounted_first_hit: torch.Tensor
    discounted_active_time: torch.Tensor
    single_cycle_value: torch.Tensor
    regenerative_value: torch.Tensor
    reset_value: torch.Tensor
    renewal_ratio: torch.Tensor
    renewal_denominator: torch.Tensor


def _policy(refractory, active_reward, hit_reward, reset_enabled):
    for name, value in (("refractory", refractory),
                        ("active_reward", active_reward), ("hit_reward", hit_reward)):
        if (isinstance(value, (bool, torch.Tensor)) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} must be a fixed nonnegative finite real")
    if not isinstance(reset_enabled, bool):
        raise ValueError("reset_enabled must be a bool")


def _decay(params):
    """Positive root lambda; rationalize the cancellation for negative mu."""
    kappa = torch.sqrt(params.mu.square() + 2.0 * params.discount * params.sigma.square())
    return torch.where(params.mu >= 0, (params.mu + kappa) / params.sigma.square(),
                       2.0 * params.discount / (kappa - params.mu))


def first_hit_laplace(distance, params):
    """G_rho(infinity,x)=E[exp(-rho*tau); tau<infinity], allowing x=0.

    Distance is relative to the fixed boundary; for an absolute initial value
    V use ``torch.log(V)-params.log_boundary`` so its boundary derivative is
    retained. The inherited PhysicalParameters domain requires rho>0.
    """
    _check_parameters(params)
    x = _tensor(distance, params.mu)
    _finite("distance", x)
    if bool((x < 0).any()):
        raise ValueError("distance must be nonnegative")
    exponent = -_decay(params) * x
    _finite("Laplace exponent", exponent)
    return torch.exp(exponent)


def perpetual_value(distance, params, *, refractory, active_reward=0.4,
                    hit_reward=1.0, reset_enabled=True):
    """Return C(x) and U(x) under one fixed trigger/delay/reset policy.

    With g(x)=G_rho(infinity,x), a=active_reward, h=hit_reward,
    C(x)=a*(1-g(x))/rho+h*g(x), eta=exp(-rho*d),
    U(x)=C(x)+g(x)*eta*C(x_r)/(1-eta*g(x_r)).
    ``expm1`` resolves both small occupation and the renewal denominator.
    No terminal reward is paid at the ends of numerical propagation steps.
    The killed control has U=C and no reset continuation. A zero waiting
    interval is admitted because x_r>0 and rho>0 still give a finite U.
    """
    xr = _check_parameters(params)
    _policy(refractory, active_reward, hit_reward, reset_enabled)
    x = _tensor(distance, params.mu)
    _finite("distance", x)
    if bool((x < 0).any()):
        raise ValueError("distance must be nonnegative")
    decay = _decay(params)
    log_g = -decay * x
    _finite("Laplace exponent", log_g)
    g = torch.exp(log_g)
    occupation = -torch.expm1(log_g) / params.discount
    cycle = active_reward * occupation + hit_reward * g
    log_gr = -decay * xr
    reset_cycle = (active_reward * -torch.expm1(log_gr) / params.discount
                   + hit_reward * torch.exp(log_gr))
    if reset_enabled:
        log_ratio = log_gr - params.discount * refractory
        _finite("renewal log ratio", log_ratio)
        ratio = torch.exp(log_ratio)
        denominator = -torch.expm1(log_ratio)
        reset_value = reset_cycle / denominator
        value = cycle + g * torch.exp(-params.discount * refractory) * reset_value
    else:
        ratio = params.mu.new_zeros(())
        denominator = params.mu.new_ones(())
        reset_value = reset_cycle
        value = cycle
    for name, item in (("renewal denominator", denominator), ("regenerative value", value),
                       ("reset value", reset_value)):
        _finite(name, item)
    if bool(denominator <= 0):
        raise FloatingPointError("renewal denominator is unresolved")
    return PerpetualValue(g, occupation, cycle, value, reset_value, ratio, denominator)


def refractory_value(remaining, params, *, refractory, active_reward=0.4,
                     hit_reward=1.0, reset_enabled=True):
    """Value before release, excluding the hit reward that was already paid.

    The reset-disabled control is an absorbing, zero-reward state. Remaining
    time must lie in the declared deterministic interval [0,refractory].
    """
    xr = _check_parameters(params)
    result = perpetual_value(xr, params, refractory=refractory, active_reward=active_reward,
                             hit_reward=hit_reward, reset_enabled=reset_enabled)
    r = _tensor(remaining, params.mu)
    _finite("remaining time", r)
    if bool(((r < 0) | (r > refractory)).any()):
        raise ValueError("remaining time must lie in [0,refractory]")
    return (torch.exp(-params.discount * r) * result.reset_value if reset_enabled
            else torch.zeros_like(r))


def basis_perpetual_value(grid, params, *, active_reward=0.4, hit_reward=1.0,
                          reset_enabled=True):
    """Integrate continuum U exactly over each declared QPR source density.

    Uniform active cells, the returning L+Exp(tail_rate) density, and uniform
    remaining-time cells are integrated analytically. The vector can be
    dotted with probability coefficients for an error comparison, but is
    NOT the perpetual resolvent of the repeatedly projected numerical chain.
    """
    if not isinstance(grid, GridSpec):
        raise TypeError("grid must be GridSpec")
    xr = _check_parameters(params)
    result = perpetual_value(xr, params, refractory=grid.refractory, active_reward=active_reward,
                             hit_reward=hit_reward, reset_enabled=reset_enabled)
    decay = _decay(params)
    edges = params.mu.new_tensor(grid.active_edges)
    width = edges[1:] - edges[:-1]
    z = decay * width
    log_g = -decay * edges[:-1] + torch.log(-torch.expm1(-z) / z)
    log_tail_g = -decay * grid.endpoint - torch.log1p(decay / grid.tail_rate)
    logs = torch.cat((log_g, log_tail_g.reshape(1)))
    g = torch.exp(logs)
    active = active_reward * -torch.expm1(logs) / params.discount + hit_reward * g
    if reset_enabled:
        active = active + g * torch.exp(-params.discount * grid.refractory) * result.reset_value
        phase_edges = params.mu.new_tensor(grid.phase_edges)
        phase_width = phase_edges[1:] - phase_edges[:-1]
        phase = (torch.exp(-params.discount * phase_edges[:-1])
                 * -torch.expm1(-params.discount * phase_width)
                 / (params.discount * phase_width) * result.reset_value)
    else:
        phase = params.mu.new_zeros(grid.phase_cells)
    values = torch.cat((active, phase))
    _finite("basis continuum values", values)
    return values
