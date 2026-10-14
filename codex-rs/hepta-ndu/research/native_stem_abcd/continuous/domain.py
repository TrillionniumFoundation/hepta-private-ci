"""R6 common continuous law and weighted R5 population adjoint. No oracle in fit."""
from pathlib import Path
import sys
import numpy as np
import torch
from scipy.stats import qmc

PARENT = Path(__file__).resolve().parents[1] / 'nonquadratic'
sys.path.insert(0, str(PARENT))
from problem import make_problem, rollout, unpack, initial_weights
from experiment import Attention, avector

SCALE = np.array([.25, .25, .8, .8])
DT = torch.float64


def rule(name):
    """Positive tensor weights approximate one fixed uniform law, not new targets."""
    if name == 'corners':
        x, w = np.array([-1., 1.]), np.array([.5, .5])
    elif name.startswith('cc'):
        n = int(name[2:])
        if n not in (3, 5, 9, 17):
            raise ValueError('unsupported nested rule')
        x = np.cos(np.pi * np.arange(n) / (n - 1)); x[n // 2] = 0.
        moments = np.zeros(n); moments[0] = 1.
        w = np.linalg.solve(np.polynomial.legendre.legvander(x, n - 1).T, moments)
    elif name == 'gl9':
        x, w = np.polynomial.legendre.leggauss(9); w = w / 2
    else:
        raise ValueError('unknown rule')
    states = np.stack(np.meshgrid(*([x] * 4), indexing='ij'), -1).reshape(-1, 4) * SCALE
    weights = np.prod(np.stack(np.meshgrid(*([w] * 4), indexing='ij'), -1), -1).reshape(-1)
    if (weights <= 0).any() or abs(weights.sum() - 1) > 1e-13:
        raise ValueError('invalid integration mass')
    return states, weights / weights.sum()


def probe(rep, power=9):
    if rep not in range(4) or power not in range(4, 13):
        raise ValueError('invalid Sobol replicate')
    return (2 * qmc.Sobol(4, scramble=True, seed=2026101461 + rep).random_base2(power) - 1) * SCALE


def check_law(states, weights):
    s, w = np.asarray(states), np.asarray(weights)
    if s.ndim != 2 or s.shape[1] != 4 or w.shape != (len(s),):
        raise ValueError('law shape')
    if not np.isfinite(s).all() or not np.isfinite(w).all() or (w < 0).any() or abs(w.sum()-1) > 1e-12:
        raise ValueError('law mass')


class Policy:
    def __init__(self, family, seed):
        self.family = family
        self.attention = Attention(seed) if family == 'attention' else None
        self.initial = avector(self.attention) if self.attention else initial_weights(seed, family)

    def tree(self, theta, p, states):
        if self.attention is None:
            return rollout(theta, p, states, self.family)
        def action(s, mode, k, bound):
            pars, offset = {}, 0
            for name, v in self.attention.named_parameters():
                pars[name] = theta[offset:offset + v.numel()].reshape(v.shape); offset += v.numel()
            return torch.func.functional_call(self.attention, pars, (s, mode, k, bound))
        return rollout(theta, p, states, policy=action)

    def value(self, theta, p, states, weights, ridge=0.):
        root = self.tree(theta, p, states)[0].reshape(-1, 2).mean(-1)
        return torch.dot(root, torch.as_tensor(weights, dtype=DT)) + .5 * ridge * theta.square().mean()


def adjoint(theta, p, states, weights, family='nonlinear', ridge=0.):
    """Exact weighted derivative; no autograd.grad. Finite tree, not general FBSDE."""
    if p.horizon != 3 or family == 'attention':
        raise ValueError('unsupported adjoint family/horizon')
    value, levels, tilts, terminal, lam = rollout(theta, p, states, family)
    w = p.tensors(); K, W, b, V, c = unpack(theta, family); deltas = []
    for k in reversed(range(3)):
        L = levels[k]
        expected = (tilts[k][..., None] * lam.reshape(-1, 2, 2)).sum(1)
        du = w['action_cost'][L['mode'], None] * L['u'] + p.gamma * expected @ w['B']
        draw = du * (1 - (L['u'] / p.bound).square())
        dh = torch.einsum('bi,bij->bj', draw, K[k, L['mode'], :, :2])
        if W is not None:
            hidden = (draw @ V) * (1 - L['z'].square()); dh = dh + hidden @ W[:, :2]
        lam = p.state_cost * L['h'] + p.gamma * expected @ w['A'] + dh
        deltas.append(draw)
    # Root masses are integration weights / two regimes, NOT uniform sample counts.
    alpha = torch.as_tensor(weights, dtype=DT).repeat_interleave(2) / 2
    deltas.reverse(); gK = []; gW = torch.zeros((4, 4), dtype=DT); gb = torch.zeros(4, dtype=DT)
    gV = torch.zeros((2, 4), dtype=DT); gc = torch.zeros(2, dtype=DT)
    for k, L in enumerate(levels):
        d = deltas[k] * alpha[:, None]
        gK.append(torch.stack([torch.einsum('bi,bj->ij', d * (L['mode'] == m)[:, None], L['s']) for m in (0, 1)]))
        if W is not None:
            hidden = (d @ V) * (1 - L['z'].square()); gW = gW + hidden.T @ L['s']; gb = gb + hidden.sum(0)
            gV = gV + d.T @ L['z']; gc = gc + d.sum(0)
        alpha = (p.gamma * alpha[:, None] * tilts[k]).reshape(-1)
    kg = torch.stack(gK)
    if family == 'scalar':
        eye = torch.eye(2, dtype=DT); grad = (kg * torch.cat((-eye, eye), -1)).sum((-1, -2)).flatten()
    elif family == 'matrix':
        grad = kg.flatten()
    else:
        grad = torch.cat((kg.flatten(), gW.flatten(), gb, gV.flatten(), gc))
    grad = grad + ridge * theta / theta.numel()
    val = (value.reshape(-1, 2).mean(-1) * torch.as_tensor(weights, dtype=DT)).sum()
    return val + .5 * ridge * theta.square().mean(), grad


def evaluate(policy, theta, p, states, chunk=512):
    """All requested points evaluated; chunking changes memory, not information."""
    values = []
    with torch.no_grad():
        for start in range(0, len(states), chunk):
            values.append(policy.tree(theta, p, states[start:start+chunk])[0].reshape(-1, 2).numpy())
    return np.concatenate(values)
