"""Trainable input-local renewal memory; no claim that media follows this law.

Between accepted packets a shared latent Brownian renewal law rotates sixteen
signed content pairs. Its coefficients depend only on previous accepted state.
The newly accepted packet is then assimilated. This is an explicit candidate
inductive bias with input-local re-anchoring, not a recovered v6 observation law.
"""

import math
import torch
from torch import nn


def count_bank(parameters, dt, mode="renewal"):
    unit = parameters.sigmoid()
    gap = .15 + 1.2 * unit[:, 0:1]
    nu = -(.2 + .8 * unit[:, 1:2])
    sigma = .2 + .45 * unit[:, 2:3]
    reset = .4 + .6 * unit[:, 3:4]
    refractory = .16 + .12 * unit[:, 4:5]
    n = torch.arange(1, 11, dtype=dt.dtype, device=dt.device)[None]
    elapsed = dt - (n - 1) * refractory
    distance = gap + (n - 1) * reset
    safe = torch.where(elapsed > 0, elapsed, torch.ones_like(elapsed))
    scale = sigma * safe.sqrt()
    a, b = (-distance - nu * safe) / scale, (-distance + nu * safe) / scale
    reflection = (-2 * nu * distance / sigma.square() + torch.special.log_ndtr(b)).clamp(max=0).exp()
    tails = torch.where(elapsed > 0, torch.special.ndtr(a) + reflection, 0.).clamp(0, 1)
    probabilities = torch.cat((torch.ones_like(tails[:, :1]), tails[:, :-1]), 1) - tails
    probabilities = probabilities.clamp(min=0)
    probabilities = probabilities / probabilities.sum(1, keepdim=True)
    if mode == "single":
        return torch.cat((probabilities[:, :1], 1 - probabilities[:, :1],
                          torch.zeros_like(probabilities[:, 2:])), 1)
    if mode == "mean":
        indices = torch.arange(10, dtype=dt.dtype, device=dt.device)[None]
        mean = (probabilities * indices).sum(1, keepdim=True)
        lower = mean.floor().clamp(0, 8).long()
        result = torch.zeros_like(probabilities)
        result.scatter_add_(1, lower, 1 - (mean - lower))
        result.scatter_add_(1, lower + 1, mean - lower)
        return result
    if mode != "renewal":
        raise ValueError("Unknown count transform")
    return probabilities


class Model(nn.Module):
    def __init__(self, family, mean, scale):
        super().__init__()
        self.family, self.mode = family, family
        self.register_buffer("mean", torch.as_tensor(mean, dtype=torch.float64))
        self.register_buffer("scale", torch.as_tensor(scale, dtype=torch.float64))
        if family == "gru":
            self.update = nn.GRUCell(41, 32)
        elif family == "ssm":
            self.rate, self.gain, self.drive = (nn.Linear(41, 32) for _ in range(3))
        elif family in ("renewal", "mean", "single"):
            self.physics = nn.Linear(32, 5)
            self.drive, self.gain = nn.Linear(41, 32), nn.Linear(41, 32)
            self.angle = nn.Parameter(torch.linspace(.15, 2.8, 16))
        elif family != "direct":
            raise ValueError("Unknown family")
        self.reader = nn.Sequential(nn.Linear(41 if family == "direct" else 73, 64),
                                    nn.Tanh(), nn.Linear(64, 16))
        self.double()

    def standardized(self, x):
        return (x - self.mean) / self.scale

    def step(self, raw, state):
        x = self.standardized(raw)
        if self.family == "direct":
            return state
        if self.family == "gru":
            return self.update(x, state)
        if self.family == "ssm":
            decay = torch.exp(-nn.functional.softplus(self.rate(x)) * raw[:, -1:])
            gain = self.gain(x).sigmoid()
            return (1 - gain) * decay * state + gain * self.drive(x).tanh()
        probabilities = count_bank(self.physics(state), raw[:, -1:], self.mode)
        n = torch.arange(10, dtype=raw.dtype, device=raw.device)[:, None]
        theta = math.pi * self.angle.sigmoid()[None]
        cosine, sine = probabilities @ torch.cos(n * theta), probabilities @ torch.sin(n * theta)
        real, imag = state[:, :16], state[:, 16:]
        evolved = torch.cat((cosine * real - sine * imag, sine * real + cosine * imag), 1)
        gain = self.gain(x).sigmoid()
        return (1 - gain) * evolved + gain * self.drive(x).tanh()

    def predict(self, raw, state):
        raw = torch.cat((raw[:, :-1], torch.zeros_like(raw[:, -1:])), 1)
        x = self.standardized(raw)
        return self.reader(x if self.family == "direct" else torch.cat((x, state), 1))

    def forward(self, x):
        state, outputs = x.new_zeros((len(x), 32)), []
        for t in range(x.shape[1]):
            state = self.step(x[:, t], state)
            outputs.append(self.predict(x[:, t], state))
        return torch.stack(outputs, 1)
