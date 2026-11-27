"""Connect one episode's task boundary to the complete finite flow.

The boundary is optimal for the stated scalar diffusion control objective.
The finite CTMC approximates that diffusion; its projected policy need not be
optimal for the CTMC or for a classification loss. The boundary and spatial
coordinates must stay fixed during an episode. The classifier constructs this
binding once per episode. A caller changing coordinates on a continued state
would need a separate transport rule; this stateless builder cannot check it.
"""

from dataclasses import dataclass
from fractions import Fraction

import torch

from qualification.hcsn_currentstate.differentiable import (
    Atom, Physics, Work, _integrals,
)
from qualification.hcsn_differentiable.neural_control import _validate, optimal_boundary


@dataclass(frozen=True)
class EpisodePhysics:
    physics: Physics
    boundary: torch.Tensor
    nodes: torch.Tensor
    initial_probability: torch.Tensor


def task_physics(theta, *, nodes=4, extent=1.5, delay=Fraction(1, 5), boundary=None):
    """Central-difference diffusion with explicit permanent upper escape.

    ``theta`` contains (mu, sigma, discount, log_reset, gain, maintenance,
    spike_cost), all FP64. ``delay`` is a fixed rational duration, excluded
    from the tensor API because this kernel has no scheduling gradient.
    Reset is linearly deposited on two interior nodes. This is a
    declared finite initial/reset law, not an exact point-reset diffusion.
    The local interpolation is differentiable away from grid knots.
    """
    if type(nodes) is not int or not 2 <= nodes <= 64 or extent <= 0:
        raise ValueError("require 2..64 spatial nodes and positive extent")
    if theta.shape != (7,) or theta.dtype != torch.float64:
        raise ValueError("seven FP64 task parameters required; delay is fixed")
    if not isinstance(delay, Fraction) or delay <= 0:
        raise ValueError("positive fixed rational delay required")
    full = torch.cat((theta[:4], theta.new_tensor([float(delay)]), theta[4:]))
    _validate(full)
    b = optimal_boundary(full) if boundary is None else boundary
    if b.ndim != 0 or not bool(torch.isfinite(b)):
        raise ValueError("finite scalar episode boundary required")
    mu, sigma, rho, reset, gain, maintenance, cost = theta.unbind()
    h = extent / (nodes + 1)
    x = torch.arange(1, nodes + 1, dtype=theta.dtype, device=theta.device) * h
    down = sigma.square() / (2*h*h) - mu / (2*h)
    up = sigma.square() / (2*h*h) + mu / (2*h)
    if not bool((down > 0) & (up > 0)):
        raise ValueError("mesh does not define positive central-difference rates")
    gap = reset - b
    if not bool((x[0] < gap) & (gap < x[-1])):
        raise ValueError("reset must lie strictly inside the interior-node hull")
    left = int(torch.searchsorted(x.detach(), gap.detach(), right=True)) - 1
    fraction = (gap - x[left]) / h
    unit = torch.eye(nodes, dtype=theta.dtype, device=theta.device)
    reset_law = (1-fraction)*unit[left] + fraction*unit[left+1]
    q = torch.diag(-(down+up)*torch.ones_like(x))
    q = q + torch.diag(up.expand(nodes-1), diagonal=1)
    q = q + torch.diag(down.expand(nodes-1), diagonal=-1)
    lower, upper = down*unit[0], up*unit[-1]
    physics = Physics(q, lower, upper, reset_law, gain*(b+x)-maintenance,
                      gain*(b+extent)-maintenance, -cost, rho, delay)
    return EpisodePhysics(physics, b, b+x, reset_law)


def finite_policy_value(physics):
    """Exact perpetual value of the declared finite delayed-reset process.

    Active running reward, event cost at hitting, no waiting reward, and
    permanent escape reward all match the complete-state kernel. This linear
    solve is a finite reference and does not use the diffusion value curve.
    """
    if not bool(physics.discount > 0):
        raise ValueError("positive discount required for perpetual values")
    q, rho = physics.generator, physics.discount
    escape = physics.escape_reward / rho
    eta = torch.exp(-rho*float(physics.delay))
    matrix = (rho*torch.eye(q.shape[0], dtype=q.dtype, device=q.device) - q
              - eta*physics.lower[:, None]*physics.reset[None, :])
    rhs = (physics.reward + physics.spike_reward*physics.lower
           + physics.upper*escape)
    return torch.linalg.solve(matrix, rhs), escape


def continuation_value(state, physics, work=None):
    """Continuation of every signed channel, including its exact pending law.

    Future physics is frozen on the same grid. Pending packets retain their
    event-time reset laws. Already paid spike rewards are not paid twice.
    Returns value at ``state.time``; the caller applies its stored discount.
    """
    work = Work() if work is None else work
    value, escape = finite_policy_value(physics)
    total = state.active @ value + state.upper*escape
    rho = physics.discount
    for packet in state.pending:
        reset_value = packet.reset @ value
        if isinstance(packet, Atom):
            if packet.time < state.time:
                raise ValueError("overdue pending atom")
            total = total + packet.mass*torch.exp(-rho*float(packet.time-state.time))*reset_value
            continue
        start = max(state.time, packet.start)
        if start >= packet.end:
            continue
        alpha = packet.alpha @ work.exponential(packet.generator*float(start-packet.start))
        g = packet.generator-rho*torch.eye(packet.generator.shape[0],
                                           dtype=rho.dtype, device=rho.device)
        _, integral = _integrals(g, packet.output[:, None], float(packet.end-start), work)
        total = total + ((alpha @ integral).squeeze(1)
                         * torch.exp(-rho*float(start-state.time))*reset_value)
    return total
