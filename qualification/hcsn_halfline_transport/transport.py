"""One point-source killed excursion, with deterministic refractory state and an identity mark."""
from dataclasses import dataclass

import torch

from qualification.hcsn_differentiable.network import LayerState
from qualification.hcsn_differentiable.operator import (
    _first_hit, _killed_interval_probability, _survivor_tail,
)


def point_state(distance, horizon, params, edges, phase_edges, mark):
    """Single batch, conditional on one active point and a fixed mark; 0<T<=delay."""
    mu, sigma = params.mu, params.sigma
    inputs = (distance, horizon, mu, sigma, edges, phase_edges, mark)
    if any(not isinstance(v, torch.Tensor) or v.dtype != torch.float64 or
           v.device != mu.device or not bool(torch.isfinite(v).all()) for v in inputs):
        raise ValueError("inputs must be finite FP64 tensors on one device")
    if any(v.ndim != 0 for v in inputs[:4]) or mark.ndim != 1 or mark.numel() < 1:
        raise ValueError("requires one point, one horizon, scalar drift and diffusion, and a vector mark")
    for values in (edges, phase_edges):
        if values.ndim != 1 or values.numel() < 2 or values.requires_grad or values[0] != 0 or not bool((values.diff() > 0).all()):
            raise ValueError("fixed edges must increase strictly from zero")
    if distance <= 0 or horizon <= 0 or horizon > phase_edges[-1] or abs(mu) > 2 or not .05 <= sigma <= 2:
        raise ValueError("requires x>0, 0<T<=delay, |mu|<=2 and 0.05<=sigma<=2")
    bins = _killed_interval_probability(distance, horizon, mu, sigma, edges[:-1], edges[1:])
    upper = _survivor_tail(distance, horizon, mu, sigma, edges[-1])
    # Subtract edges from the duration first, so the last deadline equals T exactly.
    deadlines = horizon - (phase_edges[-1] - phase_edges)
    phase = _first_hit(distance.expand_as(deadlines), deadlines, mu, sigma).diff()
    row = torch.cat((bins, upper.reshape(1), phase))
    if not bool(torch.isfinite(row).all()) or bool((row < 0).any()) or abs(row.sum() - 1) > 3e-11:
        raise FloatingPointError("unresolved point-state probability")
    return LayerState(row[None], row[None, :, None] * mark)


def _reset_distance(reset, distance, reset_margin):
    """Use the fixed upstream geometry by default and retain an explicitly provided graph."""
    if reset_margin is None:
        return torch.as_tensor(reset.margin, dtype=distance.dtype, device=distance.device)
    if (not isinstance(reset_margin, torch.Tensor) or reset_margin.ndim != 0
            or reset_margin.device != distance.device or reset_margin.dtype != distance.dtype
            or not bool(torch.isfinite(reset_margin)) or not 0 < reset_margin <= 8):
        raise ValueError("reset_margin must be a scalar FP64 tensor in (0,8] on the source device")
    return reset_margin


def released_once(process, reset, distance, deadline, edges, *, order=128, reset_margin=None):
    """Mass in each surviving active interval following exactly one release, d<T<2d."""
    import math
    import numpy as np

    if not isinstance(order, int) or order not in (64, 128):
        raise ValueError("the fixed time quadrature has order 64 or 128")
    if distance.ndim != 0 or deadline.ndim != 0 or distance <= 0 or not reset.refractory < deadline < 2*reset.refractory:
        raise ValueError("one released branch requires x>0 and d<T<2d")
    if (edges.ndim != 1 or len(edges) < 2 or edges.requires_grad or edges[0] != 0 or
            not bool(torch.isfinite(edges).all()) or not bool((edges.diff() > 0).all())):
        raise ValueError("active edges must increase strictly from zero")
    if any(v.dtype != torch.float64 or v.device != process.mu.device for v in (distance, deadline, edges)):
        raise ValueError("one-release continuation requires common FP64 tensors")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    angle = deadline.new_tensor((nodes+1)*math.pi/4)
    h = deadline-reset.refractory
    elapsed = h*angle.sin().square()
    remaining = h*angle.cos().square()
    jacobian_weight = h*deadline.new_tensor(weights*math.pi/4)*torch.sin(2*angle)
    density = process.density(elapsed, distance)
    a = _reset_distance(reset, distance, reset_margin)
    bins = _killed_interval_probability(a, remaining[:, None], process.mu, process.sigma, edges[:-1], edges[1:])
    tail = _survivor_tail(a, remaining, process.mu, process.sigma, edges[-1])
    rows = torch.cat((bins, tail[:, None]), dim=1)
    result = (rows*(density*jacobian_weight)[:, None]).sum(0)
    if not bool(torch.isfinite(result).all()) or bool((result < 0).any()):
        raise FloatingPointError("unresolved release integral")
    return result


@dataclass(frozen=True)
class OnceRenewed:
    state: LayerState
    original_survivors: torch.Tensor
    released_survivors: torch.Tensor
    first_phase: torch.Tensor
    second_phase: torch.Tensor
    first_event: torch.Tensor
    second_event: torch.Tensor
    marked_second_event: torch.Tensor


def once_renewed_state(process, reset, distance, deadline, edges, phase_edges, mark, *, reset_margin=None):
    """Full point-source successor for d<T<2d with first and second events kept separately."""
    if (phase_edges.ndim != 1 or phase_edges.numel() < 2 or phase_edges.requires_grad or
            phase_edges[0] != 0 or phase_edges[-1] != reset.refractory or not bool((phase_edges.diff() > 0).all())):
        raise ValueError("remaining-time edges must increase from zero to the physical delay")
    if mark.ndim != 1 or mark.numel() < 1:
        raise ValueError("the input mark must be a nonempty vector")
    if any(v.device != distance.device or v.dtype != distance.dtype or not bool(torch.isfinite(v).all())
           for v in (phase_edges, mark)):
        raise ValueError("finite marks and phase edges must share the point tensor dtype and device")
    a = _reset_distance(reset, distance, reset_margin)
    released = released_once(process,reset,distance,deadline,edges,reset_margin=a)
    mu, sigma = process.mu, process.sigma
    bins = _killed_interval_probability(distance,deadline,mu,sigma,edges[:-1],edges[1:])
    tail = _survivor_tail(distance,deadline,mu,sigma,edges[-1])
    survivors = torch.cat((bins,tail.reshape(1)))
    distance2 = distance+a
    first_deadlines = deadline-(reset.refractory-phase_edges)
    second_deadlines = (deadline-reset.refractory)-(reset.refractory-phase_edges)
    first = _first_hit(distance.expand_as(first_deadlines),first_deadlines,mu,sigma)
    second = _first_hit(distance2.expand_as(second_deadlines),second_deadlines,mu,sigma)
    first_phase, second_phase = first.diff(),second.diff()
    row = torch.cat((survivors+released,first_phase+second_phase))
    if (not bool(torch.isfinite(row).all()) or bool((survivors<0).any()) or bool((first_phase<0).any())
            or bool((second_phase<0).any()) or abs(row.sum()-1)>3e-11):
        raise FloatingPointError("unresolved one-reset successor")
    state = LayerState(row[None],row[None,:,None]*mark)
    return OnceRenewed(state,survivors,released,first_phase,second_phase,first[-1],second[-1],second[-1]*mark)
