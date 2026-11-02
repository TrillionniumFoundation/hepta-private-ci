"""Next-event and repeated-event operators for the SAME inherited finite CTMC.

Row convention: p'(t)=p(t)Q.  This module consumes make_flow's physical rates
and reset weights; it does not substitute a different reset/refractory law.
Dense matrix exponentials are a differentiable reference, not a fast kernel.
"""

import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2 import distribution_kernel as inherited


MAX_STATES = 128
MAX_BATCH = 4096
MAX_RATE_TIME = 2048.0


def _vector(index, size, anchor):
    return F.one_hot(torch.tensor(index, device=anchor.device), size).to(anchor.dtype)


def assemble(flow):
    """Return row Q, firing mark R, killed Q0, intensity and event destination.

    R includes firing self-transitions when instantaneous reset returns to the
    source cell. Such marks count even though they cancel in Q's net movement.
    No inverse of Q is taken: reducible and zero-event generators are allowed.
    """
    n, m = flow['grid'].cells, flow['grid'].refractory_stages
    size = n + m
    anchor = flow['mu']
    if size > MAX_STATES or anchor.numel() > MAX_BATCH:
        raise ValueError("Dense marked operator exceeds its fixed state/batch cap")
    if anchor.dtype not in (torch.float32, torch.float64):
        raise ValueError("Marked operators support float32 or float64 only")
    rates = [flow[key] for key in ('up', 'down', 'exit_rate', 'active_out', 'phase_rate')]
    if any(not bool(torch.isfinite(v).all()) or bool((v < 0).any()) for v in rates):
        raise ValueError("Finite nonnegative inherited rates required")
    up = flow['up'][..., None].expand(*anchor.shape, n - 1)
    down = flow['down'][..., None].expand_as(up)
    active = (-torch.diag_embed(flow['active_out']) + torch.diag_embed(up, offset=1)
              + torch.diag_embed(down, offset=-1))
    q0 = F.pad(active, (0, m, 0, m))
    reset = F.pad(flow['reset_weights'], (0, m))
    destination = _vector(n, size, anchor).expand(*anchor.shape, size) if m else reset
    source = _vector(n - 1, size, anchor)
    mark = flow['exit_rate'][..., None, None] * source[:, None] * destination[..., None, :]
    if m:
        phases = -torch.diag_embed(flow['phase_rate'][..., None].expand(*anchor.shape, m))
        if m > 1:
            phases = phases + torch.diag_embed(
                flow['phase_rate'][..., None].expand(*anchor.shape, m - 1), offset=1)
        q0 = q0 + F.pad(phases, (n, 0, n, 0))
        last = _vector(size - 1, size, anchor)
        q0 = q0 + flow['phase_rate'][..., None, None] * last[:, None] * reset[..., None, :]
    return dict(Q=q0 + mark, R=mark, Q0=q0, event_rate=mark.sum(-1),
                destination=destination)


def operators(flow, duration):
    """Full transition, next-event killed transition and repeated event vector.

    The killed transition includes waiting from an initially refractory state.
    Its row deficit is a probability; the repeated event vector can exceed one.
    The augmented exponential computes counts without a singular Q inverse.
    """
    matrices = assemble(flow)
    q, q0, rate = (matrices[key] for key in ('Q', 'Q0', 'event_rate'))
    duration = torch.as_tensor(duration, dtype=q.dtype, device=q.device)
    duration = torch.broadcast_to(duration, q.shape[:-2])
    if not bool(torch.isfinite(duration).all()) or bool((duration < 0).any()):
        raise ValueError("Finite nonnegative duration required")
    scale = q.abs().sum(-1).amax(-1) * duration
    if bool((scale > MAX_RATE_TIME).any()):
        raise ValueError("Dense exponential exceeds its fixed rate-duration cap")
    top = torch.cat((q, rate[..., None]), -1)
    augmented = F.pad(top, (0, 0, 0, 1))
    evolved = torch.matrix_exp(augmented * duration[..., None, None])
    killed = torch.matrix_exp(q0 * duration[..., None, None])
    return dict(**matrices, transition=evolved[..., :-1, :-1], killed=killed,
                event_vector=evolved[..., :-1, -1], survival_vector=killed.sum(-1),
                first_event_vector=1 - killed.sum(-1), duration=duration)


def values(flow, rho, cost):
    """Same-Q local discounted firing value and next-event transform.

    These are frozen-coefficient fixed-policy quantities, not task Bellman
    optima or He-Xiong equity prices. rho>0 makes the finite resolvent invertible
    even for zero-event/reducible chains. Negative firing rewards are allowed.
    """
    matrices = assemble(flow)
    q, q0, rate = (matrices[key] for key in ('Q', 'Q0', 'event_rate'))
    rho, cost = [torch.broadcast_to(torch.as_tensor(v, dtype=q.dtype, device=q.device),
                                    q.shape[:-2]) for v in (rho, cost)]
    if not bool(torch.isfinite(rho).all()) or bool((rho <= 0).any()):
        raise ValueError("Strictly positive finite discount required")
    if not bool(torch.isfinite(cost).all()):
        raise ValueError("Finite event cost required")
    eye = torch.eye(q.shape[-1], dtype=q.dtype, device=q.device)
    system = rho[..., None, None] * eye - q
    reward = (flow['boundary'] - cost)[..., None] * rate
    value = torch.linalg.solve(system, reward[..., None]).squeeze(-1)
    transform = torch.linalg.solve(rho[..., None, None] * eye - q0, rate[..., None]).squeeze(-1)
    if not bool(torch.isfinite(value).all()) or not bool(torch.isfinite(transform).all()):
        raise ArithmeticError("Nonfinite discounted marked value")
    return dict(value_vector=value, next_event_discount_vector=transform,
                reward_rate=reward, residual=(system @ value[..., None]).squeeze(-1) - reward)


def tilted(flow, duration, eta, decay=0.0):
    """Marked count PGF / multiplicative-content first-moment propagator.

    T_eta[i,j]=E_i[eta**N_t * exp(-decay*t) * 1{X_t=j}].  For content
    moments M[state,feature], advance by T_eta.T @ M. This retains moments,
    not the complete joint distribution of neural content and physical state.
    """
    matrices = assemble(flow)
    q, mark = (matrices[key] for key in ('Q', 'R'))
    duration, eta, decay = [torch.broadcast_to(
        torch.as_tensor(v, dtype=q.dtype, device=q.device), q.shape[:-2])
        for v in (duration, eta, decay)]
    if any(not bool(torch.isfinite(v).all()) for v in (duration, eta, decay)):
        raise ValueError("Finite tilted parameters required")
    if bool(((duration < 0) | (eta < 0) | (eta > 1) | (decay < 0)).any()):
        raise ValueError("Require duration>=0, eta in [0,1], decay>=0")
    identity = torch.eye(q.shape[-1], dtype=q.dtype, device=q.device)
    generator = q - (1 - eta)[..., None, None] * mark - decay[..., None, None] * identity
    if bool((generator.abs().sum(-1).amax(-1) * duration > MAX_RATE_TIME).any()):
        raise ValueError("Dense tilted exponential exceeds rate-duration cap")
    return dict(generator=generator,
                transition=torch.matrix_exp(generator * duration[..., None, None]))


def advance(probability, old_boundary, flow, duration):
    """Remap once and advance full and no-event histories from one input law.

    no_event_probability is a subprobability, never renormalized to one.
    active_mass is current occupancy and must not be called no-hit survival.
    """
    op = operators(flow, duration)
    probability = torch.as_tensor(probability, dtype=op['Q'].dtype, device=op['Q'].device)
    if probability.shape[-1] != op['Q'].shape[-1]:
        raise ValueError("Probability dimension does not match active plus refractory states")
    tolerance = max(1e-12, 128 * torch.finfo(probability.dtype).eps)
    if (not bool(torch.isfinite(probability).all()) or bool((probability < 0).any())
            or bool(((probability.sum(-1) - 1).abs() > tolerance).any())):
        raise ValueError("Finite nonnegative unit-mass initial law required")
    remap = inherited.remap_operator(old_boundary, flow)
    immediate_mark = remap['event_vector'][..., :, None] * op['destination'][..., None, :]
    no_event_remap = remap['transition'] - immediate_mark
    full = probability.unsqueeze(-2) @ remap['transition'] @ op['transition']
    killed = probability.unsqueeze(-2) @ no_event_remap @ op['killed']
    immediate = (probability * remap['event_vector']).sum(-1)
    event_vector = remap['event_vector'] + (
        remap['transition'] @ op['event_vector'][..., None]).squeeze(-1)
    no_event_probability = killed.squeeze(-2)
    survival = no_event_probability.sum(-1)
    return dict(probability=full.squeeze(-2), no_event_probability=no_event_probability,
                survival=survival, first_event=1 - survival,
                events=(probability * event_vector).sum(-1), immediate_events=immediate,
                active_mass=full.squeeze(-2)[..., :flow['grid'].cells].sum(-1),
                refractory_mass=full.squeeze(-2)[..., flow['grid'].cells:].sum(-1),
                remap=remap['transition'], no_event_remap=no_event_remap, operators=op)
