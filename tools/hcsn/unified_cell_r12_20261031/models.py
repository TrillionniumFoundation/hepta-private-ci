"""Trainable joint-law cell and two ordinary recurrent estimators."""

import torch
from torch import nn
from torch.nn import functional as F

from contract import DTYPE
from contract import as_numpy
from contract import emission_matrix
from contract import initial_raw
from contract import model_terms


class DistributionCell(nn.Module):
    def __init__(self):
        super().__init__()
        self.raw = nn.Parameter(initial_raw())
        self.logits = nn.Parameter(torch.randn(2, 6, dtype=DTYPE) * 0.05)

    def prepare(self, times, prices=False):
        terms = model_terms(self.raw, prices=prices)
        terms["emission"] = emission_matrix(self.logits)
        terms["transitions"] = torch.matrix_exp(times[:, None, None] * terms["Q"])
        return terms

    def forward(self, dt, tokens, observed):
        times, inverse = torch.unique(dt, return_inverse=True)
        terms = self.prepare(times)
        p = terms["prior"].expand(len(dt), -1)
        outputs = []
        for t in range(dt.shape[1]):
            transition = terms["transitions"][inverse[:, t]]
            p = torch.bmm(p[:, None, :], transition).squeeze(1)
            likelihood = terms["emission"][:, tokens[:, t]].T
            likelihood = torch.where(observed[:, t, None], likelihood, 1.0)
            p = p * likelihood
            p = p / p.sum(dim=-1, keepdim=True)
            outputs.append(p)
        return torch.stack(outputs, dim=1)

    def export_model(self):
        terms = as_numpy(model_terms(self.raw))
        terms["emission"] = emission_matrix(self.logits).detach().numpy()
        return terms


def input_features(dt, tokens, observed):
    symbols = F.one_hot(tokens, 7).to(DTYPE) * observed[..., None]
    return torch.cat((symbols, observed[..., None].to(DTYPE),
                      torch.log1p(dt)[..., None]), dim=-1)


class RecurrentCell(nn.Module):
    def __init__(self, kind, width=32, dim=20):
        super().__init__()
        self.kind, self.width = kind, width
        if kind == "gru":
            self.recurrence = nn.GRUCell(9, width)
        elif kind == "continuous_diagonal_ssm":
            self.input = nn.Linear(9, width)
            self.gate = nn.Linear(9, width)
            self.rates = nn.Parameter(torch.linspace(-2, 1, width))
            self.mix = nn.Linear(width, width)
        else:
            raise ValueError(kind)
        self.readout = nn.Sequential(nn.Linear(width, width), nn.Tanh(),
                                     nn.Linear(width, dim))
        self.to(dtype=DTYPE)

    def initial(self, count):
        return next(self.parameters()).new_zeros((count, self.width))

    def step(self, state, dt, tokens, observed):
        features = input_features(dt, tokens, observed)
        if self.kind == "gru":
            state = self.recurrence(features, state)
        else:
            decay = torch.exp(-F.softplus(self.rates) * dt[:, None])
            update = torch.tanh(self.input(features))
            gate = torch.sigmoid(self.gate(features))
            state = decay * state + (1 - decay) * gate * update
        hidden = torch.tanh(self.mix(state)) if self.kind != "gru" else state
        return state, torch.softmax(self.readout(hidden), dim=-1)

    def forward(self, dt, tokens, observed):
        state = self.initial(len(dt))
        outputs = []
        for t in range(dt.shape[1]):
            state, p = self.step(state, dt[:, t], tokens[:, t], observed[:, t])
            outputs.append(p)
        return torch.stack(outputs, dim=1)


def make_model(name):
    return DistributionCell() if name == "hx_distribution" else RecurrentCell(name)


def objective(predicted, batch):
    logp = predicted.clamp_min(1e-12).log()
    posterior_ce = -(batch["posterior"] * logp).sum(-1).mean()
    content = predicted.reshape(*predicted.shape[:-1], 2, -1).sum(-1)
    label_loss = F.nll_loss(content.clamp_min(1e-12).log().reshape(-1, 2),
                            batch["labels"].reshape(-1))
    return posterior_ce + 0.25 * label_loss, posterior_ce, label_loss
