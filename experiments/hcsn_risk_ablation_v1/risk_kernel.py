"""Killed finite-state first-event probabilities; never normalize survival.

The event includes a moving-boundary jump and any subsequent marked firing.
The killed generator keeps phase progression and reset after an *old* refractory
period, but removes every new event destination, including self-reset events.
The existing v2 generator uses columns; returned transitions use row vectors.
"""

import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as base


def killed_generator(flow):
    """Column generator Q_nohit = Q - destination outer event_intensity."""
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    shape = flow["mu"].shape
    active = torch.diag_embed(-flow["active_out"])
    active = active + torch.diag_embed(flow["up"][..., None].expand(*shape, n - 1), offset=1)
    active = active + torch.diag_embed(flow["down"][..., None].expand(*shape, n - 1), offset=-1)
    if not m:
        return active.transpose(-1, -2)
    phase = torch.diag_embed(-flow["phase_rate"][..., None].expand(*shape, m))
    if m > 1:
        phase = phase + torch.diag_embed(
            flow["phase_rate"][..., None].expand(*shape, m - 1), offset=1)
    release = F.pad((flow["phase_rate"][..., None] * flow["reset_weights"])[..., None, :],
                    (0, 0, m - 1, 0))
    row_generator = torch.cat((F.pad(active, (0, m)), torch.cat((release, phase), -1)), -2)
    return row_generator.transpose(-1, -2)


def survival_remap(old_boundary, flow):
    """Substochastic physical-overlap map: boundary-jump mass is killed."""
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    old_boundary, boundary = torch.broadcast_tensors(
        torch.as_tensor(old_boundary, dtype=flow["mu"].dtype, device=flow["mu"].device),
        flow["boundary"])
    if bool((old_boundary <= flow["grid"].lower).any()):
        raise ValueError("Old boundary must exceed the lower wall")
    spacing = (old_boundary - flow["grid"].lower) / n
    old_edges = flow["grid"].lower + spacing[..., None] * torch.arange(
        n + 1, device=boundary.device, dtype=boundary.dtype)
    left = torch.maximum(old_edges[..., :-1, None], flow["edges"][..., None, :-1])
    right = torch.minimum(old_edges[..., 1:, None], flow["edges"][..., None, 1:])
    overlap = (right - left).clamp_min(0) / spacing[..., None, None]
    if not m:
        return overlap
    phase = torch.eye(m, dtype=boundary.dtype, device=boundary.device)
    phase = phase.expand(*boundary.shape, m, m)
    return torch.cat((F.pad(overlap, (0, m)), F.pad(phase, (n, 0))), -2)


def _jump(power, flow, rate):
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    active, phase = power[..., :n], power[..., n:]
    result = active * (1 - flow["active_out"][..., None, :] / rate)
    result = result + F.pad(active[..., :-1] * (flow["up"] / rate)[..., None, None], (1, 0))
    result = result + F.pad(active[..., 1:] * (flow["down"] / rate)[..., None, None], (0, 1))
    if not m:
        return result
    phase_flux = phase * (flow["phase_rate"] / rate)[..., None, None]
    result = result + phase_flux[..., -1, None] * flow["reset_weights"][..., None, :]
    phase_result = phase - phase_flux + F.pad(phase_flux[..., :-1], (1, 0))
    return torch.cat((result, phase_result), -1)


def first_event_operator(flow, old_boundary, dt):
    """Return R_nohit exp(Q_nohit.T dt), using unnormalized Poisson sums.

    Arithmetic is float64 even for a float32 network. Parameter casts retain
    gradients. Fixed rate/terms and token-local chunking match the registered
    v2 contract, but Poisson weights are NOT renormalized: missing tail remains
    missing survival mass and is bounded explicitly. Floating-point roundoff
    is separate from the truncation bound. No state or matrix clipping occurs.
    """
    grid = flow["grid"]
    if grid.fixed_rate is None or grid.fixed_terms is None or grid.max_duration is None:
        raise ValueError("First-event operator requires a fixed numerical contract")
    flow = base.make_flow(*(flow[key].double() for key in
                            ("mu", "sigma", "boundary", "reset", "tau")), grid=grid)
    dt = torch.as_tensor(dt, dtype=torch.float64, device=flow["mu"].device)
    dt = torch.broadcast_to(dt, flow["mu"].shape)
    if not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
        raise ValueError("Finite nonnegative duration required")
    rate = grid.fixed_rate
    if bool((flow["active_out"] > rate).any()) or bool((flow["phase_rate"] > rate).any()):
        raise ValueError("Gross rate exceeds the fixed risk contract")
    chunks = torch.ceil(dt.detach() / grid.max_duration).clamp_min(1).long()
    chunks = chunks + (dt / chunks > grid.max_duration).long()
    if bool((chunks > grid.max_independent_chunks).any()):
        raise ValueError("Risk duration exceeds independent-chunk resource cap")
    if not grid.per_token_chunks and bool((chunks > 1).any()):
        raise ValueError("Risk duration exceeds single-step contract")
    size = grid.cells + grid.refractory_stages
    power = torch.eye(size, dtype=dt.dtype, device=dt.device).expand(*dt.shape, size, size)
    mean = rate * dt / chunks
    weight = torch.exp(-mean)
    transition = weight[..., None, None] * power
    for order in range(1, grid.fixed_terms + 1):
        power = _jump(power, flow, rate)
        weight = weight * mean / order
        transition = transition + weight[..., None, None] * power
    power = transition
    remaining = chunks - 1
    while bool((remaining > 0).any()):
        use = (remaining % 2) == 1
        transition = torch.where(use[..., None, None], transition @ power, transition)
        remaining = remaining // 2
        live = remaining > 0
        if bool(live.any()):
            power = torch.where(live[..., None, None], power @ power, power)
    remap = survival_remap(old_boundary, flow)
    survival = remap @ transition
    tail, _ = base._poisson_tail_bounds(rate * grid.max_duration, grid.fixed_terms)
    return dict(survival_transition=survival, risk_vector=1 - survival.sum(-1),
                chunks=chunks, probability_error_bound=chunks * tail,
                roundoff_included=False, survival_normalized=False,
                arithmetic_dtype="float64", generator_convention="column")


def first_event_probability(probability, operator):
    """Probability of >=1 event; differs from expected repeat-event count."""
    probability = probability.double()
    survival = (probability * operator["survival_transition"].sum(-1)).sum(-1)
    # Incoming regenerative states may have final float32 casting error. This
    # direct expectation of the risk vector avoids subtracting that mass error
    # from one; it does not renormalize killed mass or its transition.
    risk = (probability * operator["risk_vector"]).sum(-1)
    return dict(risk=risk, surviving_mass=survival,
                incoming_mass=probability.sum(-1))
