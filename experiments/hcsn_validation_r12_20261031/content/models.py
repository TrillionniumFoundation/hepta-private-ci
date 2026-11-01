"""Shared causal frontend; exact renewal-gate port; pinned real baseline blocks."""

import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .data import TASKS
from .upstream.baseline import build_baseline, match_parameter_budget


FAMILIES = ("ordinary_dual", "probit", "analytic", "lif_snn", "continuous_rnn", "cfc", "mamba1", "transformer")
WIDTH = 16


def renewal_gate(a, dt):
    """Original #4529 E[N] gate, mu=-.25,sigma=1,reset=.8,refractory=.15.

    Finite positive refractory makes the following complete finite sum exact
    for the frozen-coefficient renewal model. Computation is FP64 internally;
    no first-hit-only substitution, interval-end reset or learned physics claim.
    """
    dtype = a.dtype
    distance = F.softplus(-a.double()) + .05
    time = dt.double()
    terms = max(1, math.ceil(float(time.max().detach()) / .15))
    index = torch.arange(terms, dtype=torch.float64, device=a.device)
    gap = distance[..., None] + .8 * index
    remaining = time[..., None] - .15 * index
    safe_time = remaining.clamp_min(1e-8)
    scale = safe_time.sqrt()
    z1, z2 = (-gap + .25 * safe_time) / scale, (-gap - .25 * safe_time) / scale
    log_tail = torch.logaddexp(torch.special.log_ndtr(z1), .5 * gap + torch.special.log_ndtr(z2))
    tails = torch.where(remaining > 0, log_tail.exp().clamp_max(1), 0.)
    return (-torch.expm1(-tails.sum(-1))).to(dtype)


class ContentEncoder(nn.Module):
    """Only current and previous raw frame plus causal clocks enter the frontend."""

    def __init__(self, input_dim):
        super().__init__()
        self.input_dim = input_dim
        self.net = nn.Sequential(nn.Linear(2 * input_dim + 2, WIDTH), nn.GELU(), nn.Linear(WIDTH, WIDTH))

    def raw_features(self, x, dt):
        previous = torch.cat((torch.zeros_like(x[:, :1]), x[:, :-1]), 1)
        clock = torch.stack((torch.log1p(dt), torch.log1p(dt.cumsum(1))), -1)
        return torch.cat((x, previous, clock), -1)

    def forward(self, x, dt):
        return self.net(self.raw_features(x, dt))


class DualGate(nn.Module):
    """Same active parameters/init for ordinary, probit and renewal candidates.

    This adds one ordinary write head to the original #4529 recurrence; its
    renewal event gate is unchanged. Both heads are functions of the same
    content state, not independent financial Call/Put channels.
    """

    def __init__(self, family, seed):
        super().__init__()
        self.family = family
        rng = np.random.default_rng(seed)
        self.p = nn.ParameterDict()
        for prefix, gain in (("W", 1.), ("G", .4), ("I", .4)):
            self.p[prefix+"x"] = nn.Parameter(torch.tensor(rng.normal(0, gain/math.sqrt(WIDTH), (WIDTH, WIDTH)), dtype=torch.float32))
            self.p[prefix+"h"] = nn.Parameter(torch.tensor(rng.normal(0, .7*gain/math.sqrt(WIDTH), (WIDTH, WIDTH)), dtype=torch.float32))
            self.p[prefix+"b"] = nn.Parameter(torch.zeros(WIDTH))

    def step(self, x, h, dt):
        p = self.p
        candidate = torch.tanh(x @ p["Wx"] + h @ p["Wh"] + p["Wb"])
        a = x @ p["Gx"] + h @ p["Gh"] + p["Gb"]
        write = torch.sigmoid(x @ p["Ix"] + h @ p["Ih"] + p["Ib"])
        if self.family == "analytic":
            gate = renewal_gate(a, dt)
        elif self.family == "probit":
            # At dt=1, Phi(sqrt(2*pi)/4*a), matching sigmoid's centre slope.
            gate = -torch.expm1(dt * torch.special.log_ndtr(-math.sqrt(2*math.pi)/4 * a))
        else:
            gate = -torch.expm1(-dt * F.softplus(a))
        return h + gate * (write * candidate - h)

    def forward(self, x, dt):
        state = torch.zeros_like(x[:, 0])
        result = []
        for t in range(x.shape[1]):
            state = self.step(x[:, t], state, dt[:, t:t+1])
            result.append(state)
        return torch.stack(result, 1)


def core_configs():
    target = sum(p.numel() for p in DualGate("ordinary_dual", 0).parameters())
    configs = {name: dict(target_parameters=target, n_parameters=target, relative_gap=0.) for name in FAMILIES[:3]}
    for name in FAMILIES[3:]:
        configs[name] = match_parameter_budget(name, WIDTH, target, candidates=range(2, 25))
    return configs


class Model(nn.Module):
    def __init__(self, task, family, seed, core_config):
        super().__init__()
        self.config = dict(task=task, family=family, seed=seed, core_config=core_config)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.encoder = ContentEncoder(TASKS[task][0])
            self.readout = nn.Linear(WIDTH, TASKS[task][1])
            if family in FAMILIES[:3]:
                self.core = DualGate(family, seed+1701)
            else:
                self.core = build_baseline(family, WIDTH, hidden_width=core_config["hidden_width"])

    def forward(self, x, dt, return_states=False):
        encoded = self.encoder(x, dt)
        result = self.core(encoded, dt)
        states = result[0] if isinstance(result, tuple) else result
        logits = self.readout(states[:, -1])
        return (logits, states) if return_states else logits


def parameter_hash(module):
    import hashlib
    h = hashlib.sha256()
    for key, value in sorted(module.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        h.update(key.encode()); h.update(str((array.dtype.str, array.shape)).encode()); h.update(array.tobytes())
    return h.hexdigest()
