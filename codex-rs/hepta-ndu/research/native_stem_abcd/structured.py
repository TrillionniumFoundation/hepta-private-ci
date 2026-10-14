"""Round-2 constrained shared Stem; specialized priors are explicit, not learned facts."""
from dataclasses import replace

import numpy as np
import torch
from torch import nn

from problem import make_world


class StructuredStem(nn.Module):
    """65 shared weights mixing CE_(rho/2) and CE_(3rho/2), NOT CE_rho.

    The mixing coefficient depends only on (p*(1-p), rho), never continuation
    values. This restriction preserves order, translation, and sup stability.
    Neither basis is the exact nonzero-risk target; finite-mixture approximation
    error is possible. At risk=0 both bases equal expectation for ANY weights.
    """

    def __init__(self, seed=11):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.net = nn.Sequential(nn.Linear(2, 16), nn.Tanh(), nn.Linear(16, 1)).double()
            with torch.no_grad():
                self.net[2].weight.mul_(0.1)
                self.net[2].bias.zero_()

    @staticmethod
    def certainty(a, b, p, risk):
        # Centering prevents overflow; expm1/log1p avoid small-risk cancellation.
        mean = p * a + (1 - p) * b
        safe = torch.where(risk == 0, torch.ones_like(risk), risk)
        center = torch.maximum(a, b)
        increment = p * torch.expm1(safe * (a - center))
        increment = increment + (1 - p) * torch.expm1(safe * (b - center))
        ce = center + torch.log1p(increment) / safe
        return torch.where(risk == 0, mean, ce)

    def forward(self, v, w):
        a, b, p, risk = v[..., w['left']], v[..., w['right']], w['p'], w['risk']
        features = torch.stack((4 * p * (1 - p), risk), -1)
        gate = torch.sigmoid(self.net(features).squeeze(-1))
        low = self.certainty(a, b, p, 0.5 * risk)
        high = self.certainty(a, b, p, 1.5 * risk)
        return w['c'] + w['gamma'] * (gate * low + (1 - gate) * high)


def new_terminals(world, family='uniform'):
    """New fixed functions; none are generated from an oracle or observed errors."""
    if family not in ('uniform', 'composed', 'indicator'):
        raise ValueError('unknown terminal family')
    seed = {'uniform': 2026101401, 'composed': 2026101402, 'indicator': 2026101403}[family]
    rng = np.random.default_rng(seed)
    if family == 'uniform':
        return rng.uniform(-0.8, 0.8, (32, world.size))
    if family == 'indicator':
        return (rng.uniform(size=(32, world.size)) > 0.5).astype(np.float64)
    x, pref = np.divmod(np.arange(world.size), 3)
    bits = np.array([2 * ((x >> i) & 1) - 1 for i in range(world.bits)])
    pref = pref - 1.0
    features = [np.ones(world.size), pref, pref**2, *bits]
    features += [bits[i] * bits[(i + 1) % world.bits] for i in range(world.bits)]
    features += [bits[i] * pref for i in range(world.bits)]
    values = rng.normal(size=(32, len(features))) @ np.array(features)
    return 0.8 * values / np.max(np.abs(values), axis=1, keepdims=True)


def panel_specs():
    """Single-field interventions share EXACT terminal bytes with base where relevant."""
    return [
        ('new_uniform', 'uniform', 2, 3, 'base'),
        ('new_composed', 'composed', 2, 3, 'base'),
        ('long_horizon', 'uniform', 2, 8, 'base'),
        ('larger_state', 'uniform', 6, 3, 'base'),
        ('changed_kernel', 'uniform', 2, 3, 'kernel'),
        ('risk_zero_only', 'uniform', 2, 3, 'risk'),
        ('discount_one_only', 'uniform', 2, 3, 'discount'),
        ('cost_zero_only', 'uniform', 2, 3, 'cost'),
        ('indicator_only', 'indicator', 2, 3, 'base'),
        ('probability_joint', 'indicator', 2, 3, 'joint'),
    ]


def panel_world(bits, intervention):
    world = make_world(bits, changed=intervention == 'kernel')
    if intervention == 'base' or intervention == 'kernel':
        return world
    if intervention == 'risk':
        return replace(world, risk=np.zeros(world.size))
    if intervention == 'discount':
        return replace(world, discount=1.0)
    if intervention == 'cost':
        return replace(world, cost=np.zeros(world.size))
    if intervention == 'joint':
        return replace(world, risk=np.zeros(world.size), discount=1.0, cost=np.zeros(world.size))
    raise ValueError('unknown intervention')


def priced_decisions(pred, truth):
    """Fixed exogenous 51-price grid; no oracle-adapted near-tie construction."""
    price = np.linspace(-0.25, 0.25, 51)[:, None, None]
    pa, pb = pred[-1, ::2], pred[-1, 1::2] + price
    a, b = truth[-1, ::2], truth[-1, 1::2] + price
    choice = pa <= pb
    regret = np.where(choice, a, b) - np.minimum(a, b)
    mask = np.abs(a - b) > 1e-10
    return dict(priced_decision_regret=float(regret.mean()),
                priced_decision_accuracy=float(((choice == (a <= b))[mask]).mean()),
                priced_decision_positions=int(regret.size),
                prices_are_exogenous=True)


def invariant_probe(model, world):
    """Fixed numerical regression probes, not an exhaustive FP/continuum certificate."""
    rng = np.random.default_rng(771023)
    v = torch.tensor(rng.uniform(-2, 2, (16, world.size)), dtype=torch.float64)
    delta = torch.tensor(rng.uniform(0, 0.7, v.shape), dtype=torch.float64)
    w = world.tensor()
    with torch.no_grad():
        value, greater = model(v, w), model(v + delta, w)
        shifted = model(v + 0.375, w)
        target_shift = value + world.discount * 0.375
        low = w['c'] + w['gamma'] * torch.minimum(v[:, w['left']], v[:, w['right']])
        high = w['c'] + w['gamma'] * torch.maximum(v[:, w['left']], v[:, w['right']])
        violation = torch.maximum(low - value, value - high).clamp_min(0)
        constant = torch.full_like(v, 0.375)
        consistency = (model(constant, w) - (w['c'] + w['gamma'] * 0.375)).abs()
        excess = float((greater - value).abs().max() - w['gamma'] * delta.abs().max())
    return dict(monotonicity_max_violation=float((value - greater).clamp_min(0).max()),
                convex_hull_max_violation=float(violation.max()),
                translation_max_error=float((shifted - target_shift).abs().max()),
                constant_max_error=float(consistency.max()),
                sup_bound_excess=max(0.0, excess),
                numerical_probes_only=True)
