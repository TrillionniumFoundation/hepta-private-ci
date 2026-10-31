"""Same causal inputs, learned ordinary controls, and a nonspiking exact control."""

import torch
from torch import nn


def observed_features(history):
    dy, dt, sensor = history.unbind(-1)
    variance = torch.where(sensor > 0, sensor**2, torch.ones_like(sensor))
    return torch.stack([dy / variance, dt / variance, dy, dt, sensor], dim=-1)


def components(query):
    d, sigma, horizon, slope = query[:, :4].unbind(-1)
    modes = query.new_tensor([-.8, 0., .8])
    mu = modes[None, :] - slope[:, None]
    d, s, t = d[:, None], sigma[:, None], horizon[:, None]
    scale = s * torch.sqrt(t)
    log_f = torch.logaddexp(torch.special.log_ndtr((mu * t - d) / scale),
        2 * mu * d / s**2 + torch.special.log_ndtr((-mu * t - d) / scale))
    return torch.exp(torch.clamp(log_f, max=0.))


class RiskModel(nn.Module):
    def __init__(self, name):
        super().__init__()
        self.name = name
        if name == "analytic_filter":
            self.log_scales = nn.Parameter(torch.full((2,), -.15))
            self.prior_shift = nn.Parameter(torch.zeros(3))
        elif name == "fixed_ordinary_filter":
            self.register_buffer("log_scales", torch.zeros(2))
            self.register_buffer("prior_shift", torch.zeros(3))
        else:
            if name == "gru":
                self.recurrent = nn.GRU(5, 24, batch_first=True)
                dimension = 28
            elif name == "sufficient_mlp":
                dimension = 7
            elif name == "memoryless":
                dimension = 9
            else:
                raise ValueError(name)
            self.head = nn.Sequential(nn.Linear(dimension, 48), nn.Tanh(),
                nn.Linear(48, 48), nn.Tanh(), nn.Linear(48, 1))

    def forward(self, history, lengths, query):
        features = observed_features(history)
        a, b = features[:, :, :2].sum(1).unbind(-1)
        if self.name in ("analytic_filter", "fixed_ordinary_filter"):
            modes = query.new_tensor([-.8, 0., .8])
            prior = query.new_tensor([.3, .4, .3])
            if self.name == "fixed_ordinary_filter":
                logits = a[:, None] * modes - .5 * b[:, None] * modes**2
                posterior = torch.softmax(logits + prior.log(), -1)
            else:
                scales = self.log_scales.exp()
                logits = a[:, None] * modes * scales[0] - .5 * b[:, None] * modes**2 * scales[1]
                posterior = torch.softmax(logits + prior.log() + self.prior_shift, -1)
            return (posterior * components(query)).sum(-1)
        if self.name == "gru":
            sequence, _ = self.recurrent(features[:, :int(lengths.max())])
            state = sequence[torch.arange(len(lengths)), lengths - 1]
        elif self.name == "sufficient_mlp":
            state = torch.stack([a / 5, b / 5, a / torch.sqrt(b + 1)], dim=-1)
        else:
            state = features[torch.arange(len(lengths)), lengths - 1]
        return self.head(torch.cat([state, query[:, :4]], dim=-1)).squeeze(-1).sigmoid()


def tensor_data(data):
    return (torch.tensor(data["history"], dtype=torch.float32),
        torch.tensor(data["lengths"], dtype=torch.int64),
        torch.tensor(data["query"], dtype=torch.float32),
        torch.tensor(data["probability"], dtype=torch.float32))


def save_state(model):
    return {k: v.detach().cpu().tolist() for k, v in model.state_dict().items()}


def load_state(name, state):
    model = RiskModel(name)
    template = model.state_dict()
    model.load_state_dict({k: torch.tensor(v, dtype=template[k].dtype) for k, v in state.items()})
    return model.eval()
