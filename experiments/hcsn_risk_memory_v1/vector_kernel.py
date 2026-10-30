"""First-event survival vectors without a dense time-transition tape.

For a killed row generator A, this applies the same unnormalized, finite
Poisson polynomial in I+A/rate to the terminal vector of ones. Small chunk
counts are composed directly. Larger counts use the original matrix oracle
only for the affected tokens. No survival-transition matrix is fabricated.
"""

import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as base
from experiments.hcsn_risk_ablation_v1 import risk_kernel as oracle


PROFILE = "backward_poisson_risk_vector_v1"
MAX_DIRECT_CHUNKS = 16


def backward_jump(value, flow, rate):
    """Apply (I + Q_nohit.T/rate) to a terminal value vector, in O(states)."""
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    active, phase = value[..., :n], value[..., n:]
    result = active * (1 - flow["active_out"] / rate)
    result = result + F.pad(active[..., 1:] * (flow["up"] / rate)[..., None], (0, 1))
    result = result + F.pad(active[..., :-1] * (flow["down"] / rate)[..., None], (1, 0))
    if not m:
        return result
    released = (flow["reset_weights"] * active).sum(-1, keepdim=True)
    following = torch.cat((phase[..., 1:], released), -1)
    phase_result = phase * (1 - flow["phase_rate"] / rate)[..., None] + \
                   following * (flow["phase_rate"] / rate)[..., None]
    return torch.cat((result, phase_result), -1)


def polynomial(value, flow, mean, rate, terms):
    weight = torch.exp(-mean)
    power = value
    result = weight[..., None] * power
    for order in range(1, terms + 1):
        power = backward_jump(power, flow, rate)
        weight = weight * mean / order
        result = result + weight[..., None] * power
    return result


def first_event_vector(flow, old_boundary, dt):
    """Return actual survival/risk vectors with the original probability bound.

    Arithmetic remains float64, and missing Poisson-tail mass is not restored.
    The physical overlap remap is reused unchanged to preserve its piecewise
    derivative convention. Only its product with the survival vector is kept.
    Original matrix fallback is token-local, never selected for a whole batch
    because an unrelated token has a longer duration.
    """
    grid = flow["grid"]
    if grid.fixed_rate is None or grid.fixed_terms is None or grid.max_duration is None:
        raise ValueError("First-event vector requires the fixed numerical contract")
    flow = base.make_flow(*(flow[key].double() for key in
                            ("mu", "sigma", "boundary", "reset", "tau")), grid=grid)
    shape = flow["mu"].shape
    duration = torch.as_tensor(dt, dtype=torch.float64, device=flow["mu"].device)
    duration = torch.broadcast_to(duration, shape)
    old = torch.as_tensor(old_boundary, dtype=torch.float64, device=flow["mu"].device)
    old = torch.broadcast_to(old, shape)
    if not bool(torch.isfinite(duration).all()) or bool((duration < 0).any()):
        raise ValueError("Finite nonnegative duration required")
    if not bool(torch.isfinite(old).all()) or bool((old <= grid.lower).any()):
        raise ValueError("Finite old boundary above the lower wall required")
    rate = grid.fixed_rate
    if bool((flow["active_out"] > rate).any()) or bool((flow["phase_rate"] > rate).any()):
        raise ValueError("Gross rate exceeds the fixed risk contract")
    chunks = torch.ceil(duration.detach() / grid.max_duration).clamp_min(1).long()
    chunks = chunks + (duration / chunks > grid.max_duration).long()
    if bool((chunks > grid.max_independent_chunks).any()):
        raise ValueError("Risk duration exceeds independent-chunk resource cap")
    if not grid.per_token_chunks and bool((chunks > 1).any()):
        raise ValueError("Risk duration exceeds single-step contract")
    size = grid.cells + grid.refractory_stages
    small = chunks.reshape(-1) <= MAX_DIRECT_CHUNKS
    survival_flat = duration.new_zeros((duration.numel(), size))
    flat_old, flat_dt, flat_chunks = old.reshape(-1), duration.reshape(-1), chunks.reshape(-1)

    def selected_flow(mask):
        return base.make_flow(*(flow[key].reshape(-1)[mask] for key in
                                ("mu", "sigma", "boundary", "reset", "tau")), grid=grid)

    if bool(small.any()):
        direct_flow = selected_flow(small)
        count = flat_chunks[small]
        mean = rate * flat_dt[small] / count
        terminal = duration.new_ones((int(small.sum()), size))
        for index in range(int(count.max())):
            advanced = polynomial(terminal, direct_flow, mean, rate, grid.fixed_terms)
            terminal = torch.where((index < count)[..., None], advanced, terminal)
        remap = oracle.survival_remap(flat_old[small], direct_flow)
        survival = (remap @ terminal[..., None]).squeeze(-1)
        survival_flat = survival_flat.index_copy(0, torch.nonzero(small, as_tuple=True)[0], survival)
    large = ~small
    if bool(large.any()):
        original = oracle.first_event_operator(selected_flow(large), flat_old[large], flat_dt[large])
        survival = original["survival_transition"].sum(-1)
        survival_flat = survival_flat.index_copy(0, torch.nonzero(large, as_tuple=True)[0], survival)
    survival = survival_flat.reshape(*shape, size)
    tail, _ = base._poisson_tail_bounds(rate * grid.max_duration, grid.fixed_terms)
    return dict(survival_vector=survival, risk_vector=1 - survival,
                chunks=chunks, probability_error_bound=chunks * tail,
                roundoff_included=False, survival_normalized=False,
                arithmetic_dtype="float64", profile=PROFILE,
                direct_chunk_limit=MAX_DIRECT_CHUNKS,
                matrix_fallback_mask=(~small).reshape(shape))


def first_event_probability(probability, operator):
    probability = probability.double()
    risk = (probability * operator["risk_vector"]).sum(-1)
    survival = (probability * operator["survival_vector"]).sum(-1)
    return dict(risk=risk, surviving_mass=survival, incoming_mass=probability.sum(-1))
