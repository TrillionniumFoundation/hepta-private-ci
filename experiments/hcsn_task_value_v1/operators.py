"""Affine running-reward boundary and values of the actual finite flow.

The Brownian boundary is a frozen-local analytic policy, not the optimizer of
the finite grid or of sequence cross-entropy. The finite value solve evaluates
exactly that policy, with active reward a*x and zero refractory running reward.
All times are seconds. Impulses pay x-K. No financial option-price claim.
"""

import torch
from torch.nn import functional as F

from experiments.hcsn_conservative_acceleration_v1 import kernel as fast
from experiments.hcsn_distributional_v2 import distribution_kernel as finite
from experiments.hcsn_free_boundary_v1.oracle_torch import free_boundary


def reward_boundary(mu, sigma, rho, cost, reset, tau, slope, stages=2):
    """Reduce an affine running-reward QVI to the existing implicit root.

    U(x)=a*x/rho+a*mu/rho**2, A=1-a/rho, D=(1+rho*tau/m)**(-m).
    J=U+A/kap*exp(kap*(x-b)); matching gives the standard root at
    K_eff=(K+U(0)-D*U(r))/A. Requires A>0 and K_eff>r.
    """
    delay = (1 + rho * tau / stages).pow(-stages)
    constant = slope * mu / rho.square()
    reset_particular = slope * reset / rho + constant
    amplitude = 1 - slope / rho
    effective_cost = (cost + constant - delay * reset_particular) / amplitude
    effective_tau = stages / rho * torch.log1p(rho * tau / stages)
    if bool((amplitude <= 0).any()):
        raise ValueError("The upper-boundary family requires 1-a/rho>0")
    return free_boundary(mu, sigma, rho, effective_cost, reset, effective_tau)


def generator(flow):
    size = flow["grid"].cells + flow["grid"].refractory_stages
    rate = flow["grid"].fixed_rate
    jump = fast._jump_matrix(flow, rate)[..., :size, :size]
    eye = torch.eye(size, dtype=jump.dtype, device=jump.device)
    return rate * (jump - eye)


def value_vectors(flow, rho, cost, slope):
    """Discounted finite-generator own-policy J and immediate-action G."""
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    rho, cost, slope, boundary = torch.broadcast_tensors(rho, cost, slope, flow["boundary"])
    running = F.pad(slope[..., None] * flow["centers"], (0, m))
    event_rate = F.pad(flow["exit_rate"][..., None], (n - 1, m))
    q = generator(flow)
    eye = torch.eye(n + m, dtype=q.dtype, device=q.device)
    rhs = running + event_rate * (boundary - cost)[..., None]
    j = torch.linalg.solve(rho[..., None, None] * eye - q, rhs[..., None]).squeeze(-1)
    phase = j[..., n:]
    active_g = flow["centers"] - cost[..., None] + phase[..., :1]
    return dict(J=j, G=torch.cat((active_g, phase), -1), phase_J=phase,
                active_G=active_g, running=running)


def _base_reward_operator(flow, dt):
    """Same conditional Poisson polynomial, with count and reward integrals."""
    grid = flow["grid"]
    n, m, rate = grid.cells, grid.refractory_stages, grid.fixed_rate
    if bool((flow["active_out"] > rate).any()) or bool((flow["phase_rate"] > rate).any()):
        raise ValueError("Uniformization rate does not dominate the generator")
    if bool((dt > grid.max_duration).any()) or bool((dt < 0).any()):
        raise ValueError("Invalid chunk duration")
    jump = fast._jump_matrix(flow, rate)
    running = F.pad(flow["slope"][..., None] * flow["centers"], (0, m)) / rate
    top = torch.cat((jump[..., :-1, :], running[..., None]), -1)
    bottom = F.pad(torch.eye(2, dtype=dt.dtype, device=dt.device), (n + m, 0))
    augmented = torch.cat((top, bottom.expand(*dt.shape, 2, n + m + 2)), -2)
    weight = torch.exp(-rate * dt)
    weights = [weight]
    for order in range(1, grid.fixed_terms + 1):
        weight = weight * (rate * dt) / order
        weights.append(weight)
    polynomial, _, _ = fast._positive_polynomial(augmented, weights)
    polynomial = polynomial / sum(weights)[..., None, None]
    return polynomial[..., :n + m, :n + m], polynomial[..., :n + m, n + m:]


def reward_operator(flow, dt):
    """Return T and [expected repeat count, integrated active reward]."""
    dt = torch.broadcast_to(dt, flow["mu"].shape)
    if not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
        raise ValueError("Finite nonnegative duration required")
    chunks = torch.ceil(dt.detach() / flow["grid"].max_duration).clamp_min(1).long()
    if bool((chunks > flow["grid"].max_independent_chunks).any()):
        raise ValueError("Duration exceeds the declared numerical cap")
    duration = dt / chunks
    chunks = chunks + (duration.detach() > flow["grid"].max_duration).long()
    transition, integrated = _base_reward_operator(flow, dt / chunks)
    power_t, power_v, remaining = transition, integrated, chunks - 1
    while bool((remaining > 0).any()):
        take = remaining % 2 == 1
        combined_v = integrated + transition @ power_v
        combined_t = transition @ power_t
        integrated = torch.where(take[..., None, None], combined_v, integrated)
        transition = torch.where(take[..., None, None], combined_t, transition)
        remaining = remaining // 2
        if bool((remaining > 0).any()):
            power_v = power_v + power_t @ power_v
            power_t = power_t @ power_t
    return transition, integrated


def prepare_interval(previous, current, duration, grid):
    """Evolve held parameters first, then receive/remap the new observation.

    This order prevents an observation at t from changing the process over
    (t_previous,t). Missing observations retain the previous parameters.
    """
    old = finite.make_flow(*(previous[k] for k in ("mu", "sigma", "boundary", "r", "tau")), grid)
    new = finite.make_flow(*(current[k] for k in ("mu", "sigma", "boundary", "r", "tau")), grid)
    old["slope"] = previous["slope"]
    transition, integral = reward_operator(old, duration)
    remap = finite.remap_operator(previous["boundary"], new, 1.0, -current["K"])
    events = integral[..., 0] + (transition @ remap["event_vector"][..., None]).squeeze(-1)
    cost = (integral[..., 0] * previous["K"][..., None]
            + (transition @ (remap["event_vector"] * current["K"][..., None])[..., None]).squeeze(-1))
    reward = (integral[..., 1] + integral[..., 0] * (previous["boundary"] - previous["K"])[..., None]
              + (transition @ remap["reward_vector"][..., None]).squeeze(-1))
    values = value_vectors(new, current["rho"], current["K"], current["slope"])
    return dict(transition=transition @ remap["transition"], events=events, reward=reward, cost=cost,
                values=values, flow=new, previous_flow=old)
