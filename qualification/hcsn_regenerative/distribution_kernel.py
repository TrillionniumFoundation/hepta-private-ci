"""FP64 construction of the restricted Q P_dt R distribution operator.

dt<=d means at most one hit in each active segment. Phase releases retain the
remaining physical horizon. The exponential tail covers the whole half-line;
it can return and hit, and is never treated as absorbing escape mass.
"""

import math

import numpy as np
import torch

from .distribution import physical_time
from .tensor import _nonnegative, _positive_time_hit, finite_horizon_value


def gauss_rule(order, like):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    return (torch.as_tensor((nodes+1)/2, dtype=torch.float64, device=like.device),
            torch.as_tensor(weights/2, dtype=torch.float64, device=like.device))


def point_row(process, reset, grid, x, horizon):
    """Regular active points only; boundary/release Dirac cases stay outside."""
    x, t, _, _, _ = process.inputs(x, horizon)
    if bool(((x <= 0) | (t <= 0)).any()) or bool((t > reset.refractory).any()):
        raise ValueError("regular point rows require x>0 and 0<T<=d")
    killed = process.transition(x, t, grid.active_edges)
    edges = torch.as_tensor(grid.refractory_edges, dtype=x.dtype, device=x.device)
    # d-edge is formed first so the final deadline equals T exactly.
    deadlines = t[..., None]-(reset.refractory-edges)
    cumulative = _positive_time_hit(process, x[..., None], deadlines)
    phase = _nonnegative("projected phase law", cumulative[..., 1:]-cumulative[..., :-1])
    mass = torch.cat((killed.survivor_bins, killed.upper_tail[..., None], phase), dim=-1)
    value = finite_horizon_value(process, reset, x, t, max_terms=2)
    rewards = torch.stack((killed.hit, value.expected_discounted_hits, value.active_time), dim=-1)
    return mass, rewards


def gaussian_excess_upper(mean_minus_edge, scale):
    """Conservative bound on E[(mean+scale*Z-edge)+], without cancellation.

    Used only as a projection-distance diagnostic, not an IEEE interval proof.
    """
    if scale == 0:
        return max(0., mean_minus_edge)
    if mean_minus_edge >= 0:
        return math.nextafter(mean_minus_edge+scale/math.sqrt(2*math.pi), math.inf)
    log_value = math.log(scale)-.5*math.log(2*math.pi)-.5*(mean_minus_edge/scale)**2
    if log_value < math.log(math.ulp(0.)):
        return math.ulp(0.)
    return math.nextafter(math.exp(log_value), math.inf)


def construction_tables(process, reset, grid, duration, order):
    """Rows: finite uniform cells, exponential tail, remaining-time cells."""
    u, w = gauss_rule(order, process.mu)
    active = torch.as_tensor(grid.active_edges, dtype=torch.float64, device=process.mu.device)
    positions = active[:-1, None]+(active[1:]-active[:-1])[:, None]*u
    tail_positions = grid.active_edges[-1]-torch.log1p(-u.square())/grid.tail_rate
    positions = torch.cat((positions, tail_positions[None, :]), dim=0)
    mass, reward = point_row(process, reset, grid, positions, duration)
    basis_weight = w.expand(grid.active_size+1, -1).clone()
    basis_weight[-1] = 2*u*w
    rows = [(mass*basis_weight[..., None]).sum(1)]
    rewards = [(reward*basis_weight[..., None]).sum(1)]
    phase_rows = torch.zeros((grid.refractory_size, grid.size), dtype=torch.float64, device=process.mu.device)
    phase_rewards = torch.zeros((grid.refractory_size, 3), dtype=torch.float64, device=process.mu.device)
    edges = tuple(physical_time(r) for r in grid.refractory_edges)
    dt = physical_time(duration)
    for j, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        width = hi-lo
        # Positive part is exact interval geometry, not probability clipping.
        lower, upper = max(lo, dt)-dt, hi-dt
        if upper > lower:
            for k, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
                length = max(physical_time(0), min(upper, right)-max(lower, left))
                phase_rows[j, grid.active_size+1+k] = float(length/width)
        release_upper = min(hi, dt)
        if release_upper > lo:
            span = float(release_upper-lo)
            remaining = float(dt-release_upper)+span*u.square()
            wait = float(dt)-remaining
            if bool((remaining <= 0).any()):
                raise FloatingPointError("release subinterval is unresolved in FP64 physical time")
            released, reward = point_row(process, reset, grid, reset.margin, remaining)
            fraction = float((release_upper-lo)/width)
            phase_weight = 2*fraction*u*w
            phase_rows[j] += (released*phase_weight[:, None]).sum(0)
            discounted = reward.clone()
            discounted[:, 1:] *= torch.exp(-process.discount*wait)[:, None]
            phase_rewards[j] = (discounted*phase_weight[:, None]).sum(0)
    rows.append(phase_rows)
    rewards.append(phase_rewards)
    return torch.cat(rows), torch.cat(rewards)


def tail_excess_bounds(process, reset, grid, duration):
    """Source-wise bounds on unprojected active excess beyond endpoint L."""
    mu, sigma = float(process.mu), float(process.sigma)
    dt, endpoint = float(duration), grid.active_edges[-1]
    scale = sigma*math.sqrt(dt)
    result = [gaussian_excess_upper(hi+mu*dt-endpoint, scale) for hi in grid.active_edges[1:]]
    # For e>=0, (e+z)+ <= e+z+. The initial tail is L+Exp(lambda).
    result.append(1/grid.tail_rate+gaussian_excess_upper(mu*dt, scale))
    reset_bound = gaussian_excess_upper(reset.margin+max(mu, 0.)*dt-endpoint, scale)
    for lo, hi in zip(grid.refractory_edges[:-1], grid.refractory_edges[1:]):
        fraction = max(0., min(hi, dt)-lo)/(hi-lo)
        result.append(fraction*reset_bound)
    return torch.as_tensor(result, dtype=torch.float64, device=process.mu.device)
