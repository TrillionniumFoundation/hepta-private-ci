"""Batched conservative regenerative finite-volume flow.

The retained state is a distribution, not its mean.  Space is cell averaged on
[lower, boundary); a finite Erlang chain represents refractory residence.  The
finite CTMC is propagated by a normalized, explicitly bounded Poisson series.
The normalization is part of the declared truncation algorithm, not clipping
negative probabilities or renormalizing an otherwise invalid update.

Reset and the refractory law are fixed within an episode.  They may be jointly
learned between episodes.  Boundary/drift/noise may change at observations.
Moving-boundary remapping acts even when dt is zero.  All values here are local
fixed-policy values; task Bellman optimality is not implied.
"""

from dataclasses import dataclass
import math

import torch
from torch.nn import functional as F


@dataclass(frozen=True)
class Grid:
    cells: int = 8
    lower: float = -2.0
    refractory_stages: int = 2
    tolerance: float = 1e-10
    max_poisson_mean: float = 12.0
    max_terms: int = 160
    validate: bool = True


def _broadcast(*values):
    anchor = next((x for x in values if isinstance(x, torch.Tensor)),
                  torch.tensor(0.0, dtype=torch.float64))
    tensors = [torch.as_tensor(x, dtype=anchor.dtype, device=anchor.device)
               for x in values]
    return torch.broadcast_tensors(*tensors)


def _weights(value, centers, spacing):
    weights = (1 - (centers - value[..., None]).abs() / spacing[..., None]).clamp_min(0)
    return weights / weights.sum(-1, keepdim=True)


def make_flow(mu, sigma, boundary, reset, tau, grid=Grid()):
    """Build structured rates with parameter batch shape [...].

    Positive tau is required if refractory_stages>0.  A zero-stage grid is a
    separately declared instantaneous-reset model.  Linear interpolation of
    reset positions is piecewise differentiable, with knots at cell centers.
    """
    mu, sigma, boundary, reset, tau = _broadcast(mu, sigma, boundary, reset, tau)
    n, stages = grid.cells, grid.refractory_stages
    if n < 2 or stages < 0 or not math.isfinite(grid.lower):
        raise ValueError("Require >=2 cells, >=0 phases and finite lower bound")
    if not 0 < grid.tolerance < 0.01 or grid.max_poisson_mean <= 0:
        raise ValueError("Invalid uniformization tolerance or chunk size")
    spacing = (boundary - grid.lower) / n
    edges = grid.lower + spacing[..., None] * torch.arange(n+1, dtype=mu.dtype, device=mu.device)
    centers = (edges[..., :-1] + edges[..., 1:]) / 2
    if grid.validate:
        if not all(bool(torch.isfinite(x).all()) for x in (mu, sigma, boundary, reset, tau)):
            raise ValueError("Finite physical parameters required")
        if bool(((sigma < 0) | (boundary <= grid.lower) | (tau < 0)).any()):
            raise ValueError("Require sigma>=0, tau>=0, boundary>lower")
        if stages and bool((tau <= 0).any()):
            raise ValueError("Positive refractory mean required with phases")
        if bool(((reset < centers[..., 0]) | (reset > centers[..., -1])).any()):
            raise ValueError("Reset must lie inside the cell-center interval")
    diffusion = sigma.square() / (2 * spacing.square())
    up = diffusion + mu.clamp_min(0) / spacing
    down = diffusion + (-mu).clamp_min(0) / spacing
    exit_rate = 2 * diffusion + mu.clamp_min(0) / spacing
    active_out = (up + down)[..., None].expand(*mu.shape, n).clone()
    active_out = active_out - F.pad(down[..., None], (0, n-1))
    active_out = active_out + F.pad((exit_rate-up)[..., None], (n-1, 0))
    phase_rate = stages / tau if stages else torch.zeros_like(tau)
    return dict(mu=mu, sigma=sigma, boundary=boundary, reset=reset, tau=tau,
                grid=grid, spacing=spacing, edges=edges, centers=centers,
                reset_weights=_weights(reset, centers, spacing), up=up, down=down,
                exit_rate=exit_rate, active_out=active_out, phase_rate=phase_rate)


def initial_probability(flow, initial=0.0):
    """Subthreshold initial delta interpolated on grid centers.

    Use initial_state when an initial value may already reach the boundary;
    that API also returns the required immediate event and reward.
    """
    initial = torch.as_tensor(initial, dtype=flow['mu'].dtype, device=flow['mu'].device)
    initial = torch.broadcast_to(initial, flow['mu'].shape)
    if bool(((initial < flow['centers'][..., 0]) |
             (initial > flow['centers'][..., -1])).any()):
        raise ValueError("Subthreshold initial state must lie between grid centers")
    return F.pad(_weights(initial, flow['centers'], flow['spacing']),
                 (0, flow['grid'].refractory_stages))


def initial_state(flow, initial=0.0, reward_slope=1.0, reward_intercept=0.0):
    initial, slope, intercept, boundary = _broadcast(
        initial, reward_slope, reward_intercept, flow['boundary'])
    hit = initial >= boundary
    safe = torch.where(hit, flow['reset'], initial)
    probability = initial_probability(flow, safe)
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    destination = (F.pad(torch.ones_like(boundary)[..., None], (n, m-1))
                   if m else flow['reset_weights'])
    probability = torch.where(hit[..., None], destination, probability)
    return dict(probability=probability, boundary=boundary,
                events=hit.to(boundary.dtype),
                reward=hit.to(boundary.dtype)*(slope*initial+intercept))


def remap_operator(old_boundary, flow, reward_slope=1.0, reward_intercept=0.0):
    """Row-stochastic physical overlap map, including instantaneous firing.

    Existing refractory mass preserves its phase.  Old active mass above a
    smaller new boundary enters phase zero (or instantaneous reset).  Its
    affine reward is integrated over its actual old physical location.
    """
    old_boundary, slope, intercept, boundary = _broadcast(
        old_boundary, reward_slope, reward_intercept, flow['boundary'])
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    h0 = (old_boundary-flow['grid'].lower)/n
    e0 = flow['grid'].lower + h0[..., None]*torch.arange(n+1, dtype=boundary.dtype, device=boundary.device)
    e1 = flow['edges']
    if flow['grid'].validate and bool((old_boundary <= flow['grid'].lower).any()):
        raise ValueError("Old boundary must exceed the fixed physical lower bound")
    # Axes are old cell then new cell, matching row-vector probability states.
    left = torch.maximum(e0[..., :-1, None], e1[..., None, :-1])
    right = torch.minimum(e0[..., 1:, None], e1[..., None, 1:])
    overlap = (right-left).clamp_min(0)/h0[..., None, None]
    hit_left = torch.maximum(e0[..., :-1], boundary[..., None])
    hit_fraction = (e0[..., 1:]-hit_left).clamp_min(0)/h0[..., None]
    hit_moment = hit_fraction*(hit_left+e0[..., 1:])/2
    if m:
        active_to_phase = F.pad(hit_fraction[..., None], (0, m-1))
        active_rows = torch.cat((overlap, active_to_phase), -1)
        phase_rows = F.pad(torch.eye(m, dtype=boundary.dtype, device=boundary.device), (n, 0))
        phase_rows = phase_rows.expand(*boundary.shape, m, n+m)
        transition = torch.cat((active_rows, phase_rows), -2)
    else:
        transition = overlap + hit_fraction[..., :, None]*flow['reset_weights'][..., None, :]
    event_vector = F.pad(hit_fraction, (0, m))
    reward_vector = F.pad(slope[..., None]*hit_moment + intercept[..., None]*hit_fraction, (0, m))
    return dict(transition=transition, event_vector=event_vector,
                reward_vector=reward_vector, hit_fraction=hit_fraction,
                hit_first_moment=hit_moment)


def _poisson_tail_bounds(mean, terms):
    """Geometric majorant for P(N>terms) and E[N 1{N>terms}]."""
    if mean == 0:
        return 0.0, 0.0
    ratio = mean/(terms+2)
    if ratio >= 1:
        return math.inf, math.inf
    first = math.exp(-mean + (terms+1)*math.log(mean) - math.lgamma(terms+2))
    probability = first/(1-ratio)
    moment = first*((terms+1)/(1-ratio) + ratio/(1-ratio)**2)
    return probability, moment


def _series_terms(mean, tolerance, cap):
    terms = max(0, math.ceil(mean))
    while terms <= cap:
        tail, moment = _poisson_tail_bounds(mean, terms)
        count_bound = moment + mean*tail/(1-tail) if tail < 1 else math.inf
        if max(2*tail, count_bound) <= tolerance:
            return terms, tail, count_bound
        terms += 1
    raise RuntimeError("Uniformization term cap cannot certify requested error")


def _uniformized_jump(probability, flow, rate):
    """Apply I+Q/rate with nonnegative incoming/staying probabilities."""
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    active, phase = probability[..., :n], probability[..., n:]
    up_flux = active[..., :-1]*(flow['up']/rate)[..., None]
    down_flux = active[..., 1:]*(flow['down']/rate)[..., None]
    event = active[..., -1]*flow['exit_rate']/rate
    new_active = active*(1-flow['active_out']/rate)
    new_active = new_active + F.pad(up_flux, (1, 0)) + F.pad(down_flux, (0, 1))
    if m:
        phase_flux = phase*(flow['phase_rate']/rate)[..., None]
        new_phase = phase*(1-flow['phase_rate']/rate)[..., None]
        new_phase = new_phase + torch.cat((event[..., None], phase_flux[..., :-1]), -1)
        new_active = new_active + phase_flux[..., -1, None]*flow['reset_weights']
        result = torch.cat((new_active, new_phase), -1)
    else:
        result = new_active + event[..., None]*flow['reset_weights']
    return result, event


def propagate(probability, flow, dt):
    """Advance a fixed finite generator and integrate expected repeat events.

    Conditional Poisson truncation: sum_{k=0}^K w_k P^k / sum w_k.  Both
    probability and accumulated jump rewards use the SAME normalized weights.
    Reported analytic bounds exclude floating-point roundoff.  A detached
    dominating uniformization rate is a numerical choice, not a model parameter.
    """
    dt = torch.as_tensor(dt, dtype=probability.dtype, device=probability.device)
    dt = torch.broadcast_to(dt, probability.shape[:-1])
    if flow['grid'].validate:
        if not bool(torch.isfinite(probability).all()) or not bool(torch.isfinite(dt).all()):
            raise ValueError("Finite probability and duration required")
        if bool((dt < 0).any()) or bool((probability < 0).any()):
            raise ValueError("Nonnegative probability and duration required")
        mass_tolerance = max(1e-12, 256*torch.finfo(probability.dtype).eps)
        if bool(((probability.sum(-1)-1).abs()>mass_tolerance).any()):
            raise ValueError("Unit-mass distributions required; bounds assume unit mass")
    max_rate = max(float(flow['active_out'].detach().max()), float(flow['phase_rate'].detach().max()))
    if max_rate == 0 or not bool((dt > 0).any()):
        return dict(probability=probability, events=probability.new_zeros(probability.shape[:-1]),
                    chunks=0, terms=0, probability_l1_error_bound=0.0,
                    event_error_bound=0.0, roundoff_included=False,
                    uniformization_rate=max_rate, max_chunk_mean=0.0)
    rate = max_rate*(1+1e-6)
    max_mean = rate*float(dt.detach().max())
    chunks = max(1, math.ceil(max_mean/flow['grid'].max_poisson_mean))
    mean = max_mean/chunks
    terms, tail, conditional_count_bound = _series_terms(mean, flow['grid'].tolerance/chunks,
                                                        flow['grid'].max_terms)
    z = rate*dt/chunks
    events = probability.new_zeros(probability.shape[:-1])
    result = probability
    for _ in range(chunks):
        weight = torch.exp(-z)
        normalizer = weight
        power = result
        power_events = events.new_zeros(events.shape)
        total = weight[..., None]*power
        event_total = events.new_zeros(events.shape)
        for order in range(1, terms+1):
            power, increment = _uniformized_jump(power, flow, rate)
            power_events = power_events + increment
            weight = weight*z/order
            normalizer = normalizer+weight
            total = total+weight[..., None]*power
            event_total = event_total+weight*power_events
        result = total/normalizer[..., None]
        events = events+event_total/normalizer
    exit_ratio = float(flow['exit_rate'].detach().max())/rate
    # Subsequent chunks also receive the bounded distribution error accumulated
    # by earlier chunks.  The finite-state rate bounds every count functional.
    event_bound = chunks*exit_ratio*conditional_count_bound
    event_bound += chunks*(chunks-1)*tail*exit_ratio*mean
    return dict(probability=result, events=events, chunks=chunks, terms=terms,
                probability_l1_error_bound=2*chunks*tail,
                event_error_bound=event_bound, roundoff_included=False,
                uniformization_rate=rate, max_chunk_mean=mean)


def moments(flow, probability):
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    active, phase = probability[..., :n], probability[..., n:]
    phase_mass, eligible_mass = phase.sum(-1), active.sum(-1)
    mean = (active*flow['centers']).sum(-1)+phase_mass*flow['reset']
    second = (active*(flow['centers'].square()+flow['spacing'][..., None].square()/12)).sum(-1)
    second = second+phase_mass*flow['reset'].square()
    if m:
        remaining = torch.arange(m, 0, -1, dtype=probability.dtype, device=probability.device)
        remaining = remaining*flow['tau'][..., None]/m
        refractory_remaining = (phase*remaining).sum(-1)
    else:
        refractory_remaining = torch.zeros_like(mean)
    return dict(mean=mean, variance=second-mean.square(), second_moment=second,
                phase_mass=phase_mass, eligible_mass=eligible_mass,
                mass=probability.sum(-1), refractory_remaining=refractory_remaining,
                eligible_margin=(active*(flow['boundary'][..., None]-flow['centers'])).sum(-1),
                lower_cell_mass=active[..., 0])


def step(probability, old_boundary, mu, sigma, boundary, reset, tau, dt,
         grid=Grid(), reward_slope=1.0, reward_intercept=0.0):
    """Remap at the observation, then propagate for dt; event is an expectation.

    Events may exceed one.  Reward is undiscounted affine firing reward for this
    interval, including any zero-time boundary-jump event.  Reset/tau must be
    fixed within the episode; the caller retains these learned static parameters.
    """
    flow = make_flow(mu, sigma, boundary, reset, tau, grid)
    remap = remap_operator(old_boundary, flow, reward_slope, reward_intercept)
    remapped = torch.matmul(probability.unsqueeze(-2), remap['transition']).squeeze(-2)
    immediate_events = (probability*remap['event_vector']).sum(-1)
    immediate_reward = (probability*remap['reward_vector']).sum(-1)
    propagated = propagate(remapped, flow, dt)
    events = immediate_events+propagated['events']
    slope, intercept, b = _broadcast(reward_slope, reward_intercept, flow['boundary'])
    reward = immediate_reward+(slope*b+intercept)*propagated['events']
    return dict(flow=flow, probability=propagated['probability'], boundary=flow['boundary'],
                events=events, reward=reward, immediate_events=immediate_events,
                immediate_reward=immediate_reward, solver=propagated,
                **moments(flow, propagated['probability']))


def _hitting_transform(flow, rho):
    """Thomas solve for the finite active-chain discounted first-hit transform."""
    n = flow['grid'].cells
    diag = rho[..., None]+flow['active_out']
    lower = -flow['down']
    upper = -flow['up']
    rhs = F.pad(flow['exit_rate'][..., None], (n-1, 0))
    cs, ds = [], []
    for i in range(n):
        denominator = diag[..., i] if i == 0 else diag[..., i]-lower*cs[-1]
        d = rhs[..., i] if i == 0 else rhs[..., i]-lower*ds[-1]
        cs.append(upper/denominator if i<n-1 else torch.zeros_like(denominator))
        ds.append(d/denominator)
    solution = [ds[-1]]
    for i in range(n-2, -1, -1):
        solution.append(ds[i]-cs[i]*solution[-1])
    return torch.stack(solution[::-1], -1)


def policy_value_vectors(flow, rho, K):
    """Exact discounted policy evaluation for this finite generator.

    Erlang phases use their actual remaining-stage discount.  G on active
    states is immediate x-K plus phase-zero continuation; on refractory states
    it equals forced continuation J.  Thus J/G share the full-state domain.
    """
    rho, K, boundary = _broadcast(rho, K, flow['boundary'])
    if flow['grid'].validate and (bool((rho<=0).any()) or
                                 not bool(torch.isfinite(rho).all()) or
                                 not bool(torch.isfinite(K).all())):
        raise ValueError("Finite cost and strictly positive discount required")
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    hitting = _hitting_transform(flow, rho)
    reset_transform = (flow['reset_weights']*hitting).sum(-1)
    if m:
        factor = flow['phase_rate']/(flow['phase_rate']+rho)
        exponents = torch.arange(m, 0, -1, dtype=rho.dtype, device=rho.device)
        phase_discount = factor[..., None]**exponents
        full_delay = phase_discount[..., 0]
    else:
        full_delay = torch.ones_like(rho)
        phase_discount = rho.new_empty((*rho.shape, 0))
    renewal_denominator = 1-full_delay*reset_transform
    coefficient = (boundary-K)/renewal_denominator
    active_J = hitting*coefficient[..., None]
    reset_J = reset_transform*coefficient
    phase_J = phase_discount*reset_J[..., None]
    active_G = flow['centers']-K[..., None]+(full_delay*reset_J)[..., None]
    J = torch.cat((active_J, phase_J), -1)
    G = torch.cat((active_G, phase_J), -1)
    return dict(J=J, G=G, active_J=active_J, active_G=active_G, phase_J=phase_J,
                reset_J=reset_J, hitting_transform=hitting,
                renewal_denominator=renewal_denominator)


def finite_generator_values(flow, probability, rho, K):
    vectors = policy_value_vectors(flow, rho, K)
    n = flow['grid'].cells
    J_phase = (probability[..., n:]*vectors['phase_J']).sum(-1)
    return dict(J_total=(probability*vectors['J']).sum(-1),
                G_total=(probability*vectors['G']).sum(-1), J_phase=J_phase,
                G_eligible=(probability[..., :n]*vectors['active_G']).sum(-1),
                J_eligible=(probability[..., :n]*vectors['active_J']).sum(-1),
                eligible_margin=(probability[..., :n]*(flow['boundary'][..., None]-flow['centers'])).sum(-1),
                vectors=vectors)


def prepare_operator(mu, sigma, boundary, reset, tau, dt, grid=Grid(),
                     old_boundary=None, rho=None, K=None,
                     reward_slope=1.0, reward_intercept=0.0):
    """Precompute batched small transition/reward/value arrays, including T.

    All leading dimensions are independent parameter batches (for example
    [B,T,C]).  The same sparse uniformization is applied to each basis row.
    This changes evaluation order, not the finite generator or error contract.
    Callers may then recur only p -> p @ transition and p dot event_vector.
    """
    flow = make_flow(mu, sigma, boundary, reset, tau, grid)
    shape, size = flow['mu'].shape, grid.cells+grid.refractory_stages
    expand = lambda x: x[..., None].expand(*shape, size)
    expanded = make_flow(*(expand(flow[k]) for k in ('mu','sigma','boundary','reset','tau')), grid=grid)
    basis = torch.eye(size, dtype=flow['mu'].dtype, device=flow['mu'].device)
    basis = basis.expand(*shape, size, size)
    dt = torch.as_tensor(dt, dtype=flow['mu'].dtype, device=flow['mu'].device)
    dt = torch.broadcast_to(dt, shape)
    propagated = propagate(basis, expanded, dt[..., None])
    transition, event_vector = propagated['probability'], propagated['events']
    slope, intercept, b = _broadcast(reward_slope, reward_intercept, flow['boundary'])
    reward_vector = (slope*b+intercept)[..., None]*event_vector
    if old_boundary is not None:
        remap = remap_operator(old_boundary, flow, reward_slope, reward_intercept)
        transition = torch.matmul(remap['transition'], transition)
        event_vector = remap['event_vector']+torch.matmul(remap['transition'], event_vector[..., None]).squeeze(-1)
        reward_vector = remap['reward_vector']+torch.matmul(remap['transition'], reward_vector[..., None]).squeeze(-1)
    values = policy_value_vectors(flow, rho, K) if rho is not None and K is not None else None
    return dict(flow=flow, transition=transition, event_vector=event_vector,
                reward_vector=reward_vector, values=values,
                solver={k:v for k,v in propagated.items() if k not in ('probability','events')})


def collapse_active_mean(flow, probability):
    """Ablation: collapse active mass to its conditional mean; preserve phases.

    Two-point interpolation is required on a finite grid, so residual grid
    variance remains.  This is not the previous scalar mean/cooldown model.
    """
    n = flow['grid'].cells
    active = probability[..., :n]
    mass = active.sum(-1)
    safe_mass = torch.where(mass>0, mass, torch.ones_like(mass))
    mean = (active*flow['centers']).sum(-1)/safe_mass
    mean = torch.where(mass>0, mean, flow['reset'])
    collapsed = mass[..., None]*_weights(mean, flow['centers'], flow['spacing'])
    return torch.cat((collapsed, probability[..., n:]), -1)
