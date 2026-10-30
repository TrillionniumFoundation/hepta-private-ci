"""Reorder the registered finite Poisson polynomial without changing its model.

The augmented jump matrix carries both probabilities and expected event counts.
Positive-coefficient Paterson--Stockmeyer evaluation computes exactly the same
conditional Poisson polynomial as the frozen sparse recurrence in exact
arithmetic. Its Poisson truncation certificates remain applicable; they do not
bound floating-point or gradient error. No probabilities are clipped or silently
normalized here. The separate, explicitly tagged model profile handles roundoff.
"""

import math

import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as reference


BACKEND = "positive_augmented_poisson_ps_v1"


def _jump_matrix(flow, rate):
    n, m = flow["grid"].cells, flow["grid"].refractory_stages
    up, down = flow["up"] / rate, flow["down"] / rate
    active = torch.diag_embed(1 - flow["active_out"] / rate)
    active = active + torch.diag_embed(up[..., None].expand(*up.shape, n - 1), offset=1)
    active = active + torch.diag_embed(down[..., None].expand(*down.shape, n - 1), offset=-1)
    event = flow["exit_rate"] / rate
    if m:
        phase_rate = flow["phase_rate"] / rate
        phase = torch.diag_embed((1 - phase_rate)[..., None].expand(*up.shape, m))
        if m > 1:
            phase = phase + torch.diag_embed(
                phase_rate[..., None].expand(*up.shape, m - 1), offset=1)
        active_phase = F.pad(event[..., None, None], (0, m - 1, n - 1, 0))
        phase_active = F.pad(
            phase_rate[..., None, None] * flow["reset_weights"][..., None, :],
            (0, 0, m - 1, 0))
        transition = torch.cat((torch.cat((active, active_phase), -1),
                                torch.cat((phase_active, phase), -1)), -2)
    else:
        transition = active + F.pad(
            event[..., None, None] * flow["reset_weights"][..., None, :],
            (0, 0, n - 1, 0))
    event_vector = F.pad(event[..., None], (n - 1, m))
    top = torch.cat((transition, event_vector[..., None]), -1)
    bottom = F.pad(torch.ones_like(event)[..., None, None], (n + m, 0))
    return torch.cat((top, bottom), -2)


def _positive_polynomial(matrix, weights):
    """Evaluate sum weights[k] matrix**k using nonnegative blocks only."""
    degree = len(weights) - 1
    block_size = max(1, math.isqrt(degree + 1) + 1)
    identity = torch.eye(matrix.shape[-1], dtype=matrix.dtype, device=matrix.device)
    identity = identity.expand_as(matrix)
    powers = [identity]
    products = 0
    if degree:
        powers.append(matrix)
    for _ in range(2, min(block_size, degree + 1)):
        powers.append(torch.matmul(powers[-1], matrix))
        products += 1
    blocks = []
    for start in range(0, degree + 1, block_size):
        block = weights[start][..., None, None] * identity
        for offset in range(1, min(block_size, degree + 1 - start)):
            block = block + weights[start + offset][..., None, None] * powers[offset]
        blocks.append(block)
    result = blocks[-1]
    if len(blocks) > 1:
        stride = torch.matmul(powers[-1], matrix)
        products += 1
        for block in reversed(blocks[:-1]):
            result = block + torch.matmul(stride, result)
            products += 1
    return result, block_size, products


def _base_operator(flow, dt):
    grid = flow["grid"]
    if grid.fixed_rate is None:
        raise ValueError("Accelerated evaluation requires the registered fixed numerical contract")
    rate, terms = grid.fixed_rate, grid.fixed_terms
    maximum_rate = max(float(flow["active_out"].detach().max()),
                       float(flow["phase_rate"].detach().max()))
    if not math.isfinite(maximum_rate) or maximum_rate > rate:
        raise ValueError("Gross rate exceeds the fixed uniformization contract")
    limit = dt.new_tensor(grid.max_duration)
    if not bool(torch.isfinite(dt).all()) or bool(((dt < 0) | (dt > limit)).any()):
        raise ValueError("Duration exceeds the fixed uniformization contract")
    maximum_mean = rate * float(limit)
    tail, moment = reference._poisson_tail_bounds(maximum_mean, terms)
    count_bound = moment + maximum_mean * tail / (1 - tail) if tail < 1 else math.inf
    if max(2 * tail, count_bound) > grid.tolerance:
        raise ValueError("Fixed term count does not certify the declared duration/tolerance")
    z = rate * dt
    weight = torch.exp(-z)
    weights, normalizer = [weight], weight
    for order in range(1, terms + 1):
        weight = weight * z / order
        weights.append(weight)
        normalizer = normalizer + weight
    augmented = _jump_matrix(flow, rate)
    polynomial, block_size, products = _positive_polynomial(augmented, weights)
    polynomial = polynomial / normalizer[..., None, None]
    size = grid.cells + grid.refractory_stages
    solver = dict(terms=terms, probability_l1_error_bound=2 * tail,
                  event_error_bound=count_bound, roundoff_included=False,
                  uniformization_rate=rate, max_chunk_mean=maximum_mean,
                  numerical_configuration="fixed_neural_contract",
                  backend=BACKEND, polynomial_block_size=block_size,
                  base_dense_matrix_products=products)
    return dict(transition=polynomial[..., :size, :size],
                event_vector=polynomial[..., :size, size], solver=solver)


def _independent_operator(flow, dt):
    """Use only each token's duration to select and compose its fixed chunks."""
    grid = flow["grid"]
    limit = dt.new_tensor(grid.max_duration)
    if not bool(torch.isfinite(dt).all()) or bool((dt < 0).any()):
        raise ValueError("Independent chunks require finite nonnegative duration")
    raw_chunks = torch.ceil(dt.detach() / limit).clamp_min(1)
    if bool((raw_chunks > grid.max_independent_chunks).any()):
        raise ValueError("Duration exceeds the declared independent-chunk resource cap")
    chunks = raw_chunks.to(torch.int64)
    chunk_dt = dt / chunks.to(dt.dtype)
    chunks = chunks + (chunk_dt.detach() > limit).to(torch.int64)
    if bool((chunks > grid.max_independent_chunks).any()):
        raise ValueError("Represented duration exceeds the independent-chunk resource cap")
    chunk_dt = dt / chunks.to(dt.dtype)
    base = _base_operator(flow, chunk_dt)
    transition, events = base["transition"], base["event_vector"]
    power_transition, power_events = transition, events
    remaining, rounds = chunks - 1, 0
    while bool((remaining > 0).any()):
        use = (remaining % 2) == 1
        combined_events = events + torch.matmul(transition, power_events[..., None]).squeeze(-1)
        combined_transition = torch.matmul(transition, power_transition)
        events = torch.where(use[..., None], combined_events, events)
        transition = torch.where(use[..., None, None], combined_transition, transition)
        remaining = remaining // 2
        live = remaining > 0
        if bool(live.any()):
            doubled_events = power_events + torch.matmul(
                power_transition, power_events[..., None]).squeeze(-1)
            doubled_transition = torch.matmul(power_transition, power_transition)
            power_events = torch.where(live[..., None], doubled_events, power_events)
            power_transition = torch.where(live[..., None, None], doubled_transition, power_transition)
        rounds += 1
    count = chunks.to(dt.dtype)
    solver = dict(base["solver"])
    tail = solver["probability_l1_error_bound"] / 2
    solver.update(chunks=chunks, chunk_duration=chunk_dt,
                  probability_l1_error_bound=2 * count * tail,
                  event_error_bound=count * solver["event_error_bound"]
                      + count * (count - 1) * tail * solver["max_chunk_mean"],
                  numerical_configuration="fixed_rate_terms_independent_token_chunks",
                  scheduling_binary_rounds=rounds,
                  max_independent_chunks=grid.max_independent_chunks)
    return dict(transition=transition, event_vector=events, solver=solver)


def prepare_operator(mu, sigma, boundary, reset, tau, dt, grid=reference.Grid(),
                     old_boundary=None, rho=None, K=None,
                     reward_slope=1.0, reward_intercept=0.0):
    """Drop-in fixed-contract operator, with the original flow/remap/value laws.

    This is a computational backend. It introduces no new physical parameter,
    policy, reward, fitted weight, truncation choice, or future-dependent batch
    adaptation. Its derivative is the derivative of this very polynomial.
    """
    flow = reference.make_flow(mu, sigma, boundary, reset, tau, grid)
    if grid.fixed_rate is None:
        raise ValueError("Accelerated evaluation requires a fixed numerical contract")
    dt = torch.as_tensor(dt, dtype=flow["mu"].dtype, device=flow["mu"].device)
    dt = torch.broadcast_to(dt, flow["mu"].shape)
    composite = _independent_operator(flow, dt) if grid.per_token_chunks else _base_operator(flow, dt)
    transition, event_vector = composite["transition"], composite["event_vector"]
    slope, intercept, b = reference._broadcast(reward_slope, reward_intercept, flow["boundary"])
    reward_vector = (slope * b + intercept)[..., None] * event_vector
    if old_boundary is not None:
        remap = reference.remap_operator(old_boundary, flow, reward_slope, reward_intercept)
        transition = torch.matmul(remap["transition"], transition)
        event_vector = remap["event_vector"] + torch.matmul(
            remap["transition"], event_vector[..., None]).squeeze(-1)
        reward_vector = remap["reward_vector"] + torch.matmul(
            remap["transition"], reward_vector[..., None]).squeeze(-1)
    values = reference.policy_value_vectors(flow, rho, K) if rho is not None and K is not None else None
    return dict(flow=flow, transition=transition, event_vector=event_vector,
                reward_vector=reward_vector, values=values, solver=composite["solver"])
