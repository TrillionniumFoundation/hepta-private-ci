"""R3: exact primitive of a bounded piecewise-linear derivative. No quadrature."""
import numpy as np
import torch
from torch import nn


class IntegralStem(nn.Module):
    """65 learned weights define knot derivatives, not an exact CE expert.

    q(u,p)=sigmoid(logit(p)+u*F_theta(u,2p-1)), sampled on [-4,4].
    F is symmetrized under (u,z)->(-u,-z); node zero is exactly p.
    Linear interpolation and constant tails define the actual derivative field.
    CE=b+integral_0^(a-b) q(rho*s,p) ds, with its analytic PWL primitive.
    """
    def __init__(self, seed=11, intervals=64):
        super().__init__()
        if not isinstance(intervals, int) or intervals < 4 or intervals > 256 or intervals % 2:
            raise ValueError('even interval count in [4,256] required')
        self.intervals = intervals
        self.radius = 4.0
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.net = nn.Sequential(nn.Linear(2, 16), nn.Tanh(), nn.Linear(16, 1)).double()
            with torch.no_grad():
                self.net[2].weight.mul_(0.1)
                self.net[2].bias.zero_()
        self.register_buffer('knots', torch.linspace(-4, 4, intervals + 1, dtype=torch.float64))

    def knot_values(self, p):
        u = self.knots.expand(p.numel(), -1)
        z = (2 * p - 1).unsqueeze(-1).expand_as(u)
        features = torch.stack((u, z), -1)
        field = 0.5 * (self.net(features) + self.net(-features)).squeeze(-1)
        logits = (torch.log(p) - torch.log1p(-p)).unsqueeze(-1)
        q = torch.sigmoid(logits + u * field)
        return torch.where(u == 0, p.unsqueeze(-1), q)

    def primitive(self, u, p):
        """Integral_0^u (q(v,p)-p)dv; exact segment areas, constant tails.

        Subtract p and integrate away from zero to avoid near-zero cancellation.
        The model remains differentiable at knots (q itself is continuous).
        """
        q = self.knot_values(p) - p.unsqueeze(-1)
        mid = self.intervals // 2
        branches = torch.stack((q[:, mid:], q[:, :mid + 1].flip(-1)), 0)
        h = 2 * self.radius / self.intervals
        areas = h * (branches[..., :-1] + branches[..., 1:]) / 2
        cumulative = torch.cat((torch.zeros_like(areas[..., :1]), areas.cumsum(-1)), -1)
        index = (u.abs() / h).floor().long().clamp(max=mid - 1)
        length = u.abs().clamp(max=self.radius) - index * h
        def lookup(values, offset=0):
            plus = values[0].unsqueeze(0).expand(u.shape[0], -1, -1)
            minus = values[1].unsqueeze(0).expand_as(plus)
            chosen = torch.where((u < 0).unsqueeze(-1), minus, plus)
            return chosen.gather(-1, (index + offset).unsqueeze(-1)).squeeze(-1)
        q0, q1, area = lookup(branches), lookup(branches, 1), lookup(cumulative)
        partial = q0 * length + (q1 - q0) * length.square() / (2 * h)
        tails = torch.where(u.abs() > self.radius, u.abs() - self.radius, torch.zeros_like(u))
        endpoint = torch.where(u < 0, branches[1, :, -1], branches[0, :, -1])
        sign = torch.where(u < 0, -torch.ones_like(u), torch.ones_like(u))
        return sign * (area + partial + tails * endpoint)

    def certainty(self, a, b, p, risk):
        mean = p * a + (1 - p) * b
        safe = torch.where(risk == 0, torch.ones_like(risk), risk)
        correction = self.primitive(risk * (a - b), p) / safe
        return mean + correction

    def forward(self, v, w):
        return w['c'] + w['gamma'] * self.certainty(
            v[..., w['left']], v[..., w['right']], w['p'], w['risk'])


class ScalarIntegralStem(IntegralStem):
    """One-parameter calibration control; not a 65-weight family comparison."""
    def __init__(self, seed=0, intervals=64):
        super().__init__(seed, intervals)
        del self.net
        self.slope = nn.Parameter(torch.tensor(0.0, dtype=torch.float64))

    def knot_values(self, p):
        u = self.knots.expand(p.numel(), -1)
        logits = (torch.log(p) - torch.log1p(-p)).unsqueeze(-1)
        q = torch.sigmoid(logits + u * self.slope)
        return torch.where(u == 0, p.unsqueeze(-1), q)


def fresh_terminals(world, family):
    """R3 fixed public generators; no reference-value/error-dependent generation."""
    seeds = {'uniform': 2026101431, 'composed': 2026101432, 'indicator': 2026101433}
    if family not in seeds:
        raise ValueError('unknown terminal family')
    rng = np.random.default_rng(seeds[family])
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


def representation_witness(intervals):
    """Analytic expressivity witness, NOT trained weights or an efficacy observation."""
    model = IntegralStem(intervals=intervals)
    with torch.no_grad():
        for p in model.parameters():
            p.zero_()
        model.net[2].bias.fill_(1.0)
    return model
