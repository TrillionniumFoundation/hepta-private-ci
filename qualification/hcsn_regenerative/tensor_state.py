"""Differentiable projected state law for the bounded fixed-reset generator.

A requested projection has an explicit upper tail and refractory remaining
physical time. It is not a closed finite-bin recurrent Markov approximation.
"""

from dataclasses import dataclass

import numpy as np
import torch

from .tensor import TensorDiffusion, _as, _finite, _nonnegative, _positive_time_hit, _terms


@dataclass(frozen=True)
class RegenerativeTransition:
    active_bins: torch.Tensor
    upper_tail: torch.Tensor
    refractory_bins: torch.Tensor
    refractory_edges: torch.Tensor
    first_hit_probability: torch.Tensor
    expected_hits: torch.Tensor
    active_probability: torch.Tensor
    mass_residual: torch.Tensor
    renewal_tail_bound: float
    quadrature_error: torch.Tensor
    terms: int


def _convolution(process, distance, remaining, reset, edges, order):
    """Integrate f_distance(s) K_(H-s)(a,.) using s=H*u^2."""
    nodes, weights = np.polynomial.legendre.leggauss(order)
    u = _as((nodes+1)/2, distance)
    weight = _as(weights/2, distance)
    positive = remaining > 0
    horizon = torch.where(positive, remaining, torch.ones_like(remaining))
    time = horizon[..., None]*u.square()
    mu, sigma, q = torch.broadcast_tensors(process.mu, process.sigma, process.discount)
    # The quadrature axis must remain separate from the cell/batch axes.
    mu, sigma, q, _ = torch.broadcast_tensors(mu, sigma, q, distance)
    quadrature_process = TensorDiffusion(mu[..., None], sigma[..., None], q[..., None])
    density = quadrature_process.density(time, distance[..., None])
    successor = quadrature_process.transition(reset.margin, horizon[..., None]-time, edges)
    mass = torch.cat((successor.survivor_bins, successor.upper_tail[..., None]),dim=-1)
    value = (mass*(density*2*horizon[..., None]*u*weight)[...,None]).sum(-2)
    return torch.where(positive[...,None] & (distance > 0)[...,None],value,torch.zeros_like(value))


def regenerative_transition(process,reset,x,horizon,edges,*,refractory_edges=None,quadrature_order=64,max_terms=64):
    """Finite renewal successor with order-doubling and analytic mass guards.

    Values and gradients are those of the declared quadrature, not an exact
    continuum certificate. Underresolved low-noise/near-boundary cases reject.
    Reset, edges, quadrature order and refractory are fixed hyperparameters.
    """
    x,t,_,_,_ = process.inputs(x,horizon)
    terms = _terms(reset,t,max_terms)
    if isinstance(quadrature_order,bool) or not isinstance(quadrature_order,int) or not 16 <= quadrature_order <= 512:
        raise ValueError("quadrature_order must be a fixed integer in [16,512]")
    initial = process.transition(x,t,edges)
    remaining_edges = _as([0.,reset.refractory] if refractory_edges is None else refractory_edges,x)
    if (remaining_edges.requires_grad or remaining_edges.ndim != 1 or remaining_edges.numel()<2
            or not bool(torch.isfinite(remaining_edges).all()) or bool(remaining_edges[0] != 0)
            or bool(remaining_edges[-1] != reset.refractory) or not bool((torch.diff(remaining_edges)>0).all())):
        raise ValueError("fixed remaining-time edges must increase from zero to refractory")
    active = torch.cat((initial.survivor_bins,initial.upper_tail[...,None]),dim=-1)
    refractory = torch.zeros(x.shape+(remaining_edges.numel()-1,),dtype=x.dtype,device=x.device)
    expected_hits = torch.zeros_like(x)
    quadrature_error = torch.zeros_like(x)
    analytical_active = process.survival(x,t)
    for n in range(1,terms+1):
        distance = x+(n-1)*reset.margin
        release_horizon = t-n*reset.refractory
        expected_hits = expected_hits+_positive_time_hit(process,distance,t-(n-1)*reset.refractory)
        analytical_active = analytical_active+_positive_time_hit(process,distance,release_horizon)-_positive_time_hit(process,distance+reset.margin,release_horizon)
        # The initial hit atom releases exactly at d and is active then.
        released = release_horizon >= 0
        atom_mask = (distance == 0) & released
        if bool(atom_mask.any()):
            safe_time = torch.where(released,release_horizon,torch.ones_like(release_horizon))
            # Release-time atoms are evaluated without surrogate time gradients.
            atom = process.transition(reset.margin,safe_time,edges)
            atom_mass = torch.cat((atom.survivor_bins,atom.upper_tail[...,None]),dim=-1)
            active = active+torch.where(atom_mask[...,None],atom_mass,torch.zeros_like(atom_mass))
        if bool(((distance > 0) & (release_horizon > 0)).any()):
            coarse = _convolution(process,distance,release_horizon,reset,edges,quadrature_order)
            fine = _convolution(process,distance,release_horizon,reset,edges,2*quadrature_order)
            active = active+fine
            quadrature_error = quadrature_error+(fine-coarse).abs().sum(-1)
        left = release_horizon[...,None]+remaining_edges[:-1]
        right = release_horizon[...,None]+remaining_edges[1:]
        mu,sigma,q,_ = torch.broadcast_tensors(process.mu,process.sigma,process.discount,x)
        phase_process = TensorDiffusion(mu[...,None],sigma[...,None],q[...,None])
        contribution = (_positive_time_hit(phase_process,distance[...,None],right)
                        -_positive_time_hit(phase_process,distance[...,None],left))
        refractory = refractory+contribution
    _finite("active state",active)
    _nonnegative("refractory state",refractory)
    _nonnegative("active state",active)
    total_active = active.sum(-1)
    residual = 1-total_active-refractory.sum(-1)
    tolerance = 5e-5 if x.dtype == torch.float32 else 2e-8
    if (bool((quadrature_error>tolerance).any()) or bool((residual.abs()>tolerance).any())
            or bool(((total_active-analytical_active).abs()>tolerance).any())):
        raise FloatingPointError("regenerative successor quadrature/mass unresolved; refine explicitly")
    return RegenerativeTransition(active[...,:-1],active[...,-1],refractory,remaining_edges,
                                  initial.hit,expected_hits,total_active,residual,0.,quadrature_error,terms)
