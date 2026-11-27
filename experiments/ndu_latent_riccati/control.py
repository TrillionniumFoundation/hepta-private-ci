"""Joint continuous generation/valuation dynamics and local Riccati control.

This is a nonlinear receding-horizon approximation. The discrete affine LQ
subproblem is solved exactly; it is not an exact global nonlinear FBSDE solve.
Inference sees context estimates only. Truth is accepted by the training loss,
never by a controller. State is (six facts, one style, six valuation states).
"""

import torch
from torch import nn


class Flow(nn.Module):
    """Conditional vector field with an analytic, differentiable state Jacobian."""

    def __init__(self, context_dim=32):
        super().__init__()
        self.l1 = nn.Linear(7 + context_dim + 2, 64)
        self.l2 = nn.Linear(64, 64)
        self.l3 = nn.Linear(64, 7)

    def forward(self, z, t, context, jacobian=False):
        time = torch.as_tensor(t, dtype=z.dtype, device=z.device).expand(len(z), 1)
        features = torch.cat((z, context, time, time.square()), dim=-1)
        h1 = self.l1(features).tanh()
        h2 = self.l2(h1).tanh()
        velocity = self.l3(h2)
        if not jacobian:
            return velocity
        j1 = (1 - h1.square()).unsqueeze(-1) * self.l1.weight[:, :7]
        j2 = (1 - h2.square()).unsqueeze(-1) * (self.l2.weight @ j1)
        return velocity, self.l3.weight @ j2


class FreeController(nn.Module):
    """Unstructured comparator with the identical generation/valuation actuators."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(13 + 32 + 6 + 1, 64), nn.Tanh(),
                                 nn.Linear(64, 64), nn.Tanh(), nn.Linear(64, 13))
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, x, t, context, target):
        time = x.new_full((len(x), 1), t)
        return self.net(torch.cat((x, context, target, time), -1))


def affine_lqr(F, G, b, Q, q, R, H, h, steps=4, cross=True, rank=None):
    """Return first affine feedback u=-Kx-k for a finite discrete LQ problem.

    x_next=F x+G u+b, stage cost .5*x'Q*x+q'x+.5*u'R*u.
    Q/R already contain dt. The recursion supports batches and autograd.
    Removing cross terms or truncating eigenvalues is explicitly approximate.
    """
    S, s = H, h
    Ft, Gt = F.transpose(-1, -2), G.transpose(-1, -2)
    for _ in range(steps):
        if not cross:
            mask = torch.ones_like(S)
            mask[:, :7, 7:] = 0
            mask[:, 7:, :7] = 0
            S = S * mask
        if rank is not None:
            values, vectors = torch.linalg.eigh(S)
            S = (vectors[..., -rank:] * values[..., -rank:].clamp_min(0).unsqueeze(-2)) @ vectors[..., -rank:].transpose(-1, -2)
        control_hessian = R + Gt @ S @ G
        K = torch.linalg.solve(control_hessian, Gt @ S @ F)
        residual = (S @ b.unsqueeze(-1)).squeeze(-1) + s
        k = torch.linalg.solve(control_hessian, (Gt @ residual.unsqueeze(-1))).squeeze(-1)
        new_S = Q + Ft @ S @ F - (Ft @ S @ G) @ K
        new_s = q + (Ft @ residual.unsqueeze(-1)).squeeze(-1) - ((Ft @ S @ G) @ k.unsqueeze(-1)).squeeze(-1)
        S, s = (new_S + new_S.transpose(-1, -2)) / 2, new_s
    return K, k, S, s


def joint_dynamics(flow, x, t, context, target, need_jacobian=False):
    z, p = x[:, :7], x[:, 7:]
    if need_jacobian:
        v, jv = flow(z, t, context, jacobian=True)
    else:
        v = flow(z, t, context)
    gain = 1.25 * p.tanh()
    correction = gain * (target - z[:, :6])
    dz = v + torch.cat((correction, torch.zeros_like(z[:, 6:])), -1)
    drift = torch.cat((dz, -0.25 * p), -1)
    if not need_jacobian:
        return drift
    A = x.new_zeros((len(x), 13, 13))
    A[:, :7, :7] = jv
    A[:, :6, :6] -= torch.diag_embed(gain)
    A[:, :6, 7:] = torch.diag_embed(1.25 * (1 - p.tanh().square()) * (target - z[:, :6]))
    A[:, 7:, 7:] = -0.25 * torch.eye(6, dtype=x.dtype, device=x.device)
    return drift, A


def quadratic_cost(x, target):
    """PSD Gauss-Newton local model of bounded p-dependent valuation.

    ell_state=.5 sum exp(.5*tanh(p_i))*(z_i-target_i)^2 + .025||p||^2.
    p can change internal valuation, but cannot change heldout truth or scoring.
    """
    z, p = x[:, :6], x[:, 7:]
    root_weight = torch.exp(0.25 * p.tanh())
    residual = root_weight * (z - target)
    J = x.new_zeros((len(x), 6, 13))
    J[:, :, :6] = torch.diag_embed(root_weight)
    J[:, :, 7:] = torch.diag_embed(0.25 * (1 - p.tanh().square()) * residual)
    regularizer = torch.diag(x.new_tensor([0.] * 7 + [0.05] * 6))
    Q = J.transpose(-1, -2) @ J + regularizer
    gradient = (J.transpose(-1, -2) @ residual.unsqueeze(-1)).squeeze(-1)
    gradient = gradient + (regularizer @ x.unsqueeze(-1)).squeeze(-1)
    q = gradient - (Q @ x.unsqueeze(-1)).squeeze(-1)
    return Q, q


def riccati_action(flow, x, t, context, target, dt, arm='ndu', lookahead=4):
    drift, A = joint_dynamics(flow, x, t, context, target, need_jacobian=True)
    identity = torch.eye(13, dtype=x.dtype, device=x.device)
    F = identity + dt * A
    b = dt * (drift - (A @ x.unsqueeze(-1)).squeeze(-1))
    actuator = x.new_ones(13)
    actuator[6] = 0  # Style is generated by the common flow, not optimized away.
    if arm == 'fixed_valuation_mpc':
        actuator[7:] = 0
    G = (dt * torch.diag(actuator)).expand(len(x), 13, 13)
    Q, q = quadratic_cost(x, target)
    R = dt * torch.diag(x.new_tensor([0.25] * 7 + [0.10] * 6))
    K, k, S, s = affine_lqr(F, G, b, dt * Q, dt * q, R, 2 * Q, 2 * q,
                           steps=min(lookahead, max(1, round((1 - t) / dt))),
                           cross=arm != 'ndu_no_cross', rank=3 if arm == 'ndu_rank3' else None)
    action = -((K @ x.unsqueeze(-1)).squeeze(-1) + k)
    return action * actuator, {'S': S, 's': s}


def rollout(flow, context, target, noise, steps=8, arm='flow', actor=None,
            strength=2.0, lookahead=4, return_trace=False):
    """No label/target-output argument exists: target is the public encoder estimate."""
    dt = 1 / steps
    initial = torch.cat((target + 0.5 * noise[:, :6], noise[:, 6:]), -1)
    x = torch.cat((initial, noise.new_zeros((len(noise), 6))), -1)
    effort = noise.new_zeros(len(noise))
    trace = []
    for index in range(steps):
        t = index * dt
        if arm in {'ndu', 'fixed_valuation_mpc', 'ndu_no_cross', 'ndu_rank3'}:
            action, _ = riccati_action(flow, x, t, context, target, dt, arm, lookahead)
        elif arm == 'free_joint':
            action = actor(x, t, context, target)
            action = action * x.new_tensor([1.] * 6 + [0.] + [1.] * 6)
        elif arm == 'guidance':
            action = torch.cat((strength * (target - x[:, :6]), x.new_zeros((len(x), 7))), -1)
        elif arm == 'flow':
            action = torch.zeros_like(x)
        else:
            raise ValueError(arm)
        drift = joint_dynamics(flow, x, t, context, target)
        cost = 0.125 * action[:, :7].square().sum(-1) + 0.05 * action[:, 7:].square().sum(-1)
        effort = effort + dt * cost
        x = x + dt * (drift + action)
        if return_trace:
            trace.append(x.detach().clone())
    result = {'state': x[:, :7], 'p': x[:, 7:], 'effort': effort}
    if return_trace:
        result['trace'] = torch.stack(trace, 1)
    return result
