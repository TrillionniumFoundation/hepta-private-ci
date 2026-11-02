"""Full posterior enters a trained head; ordinary same-Q realization is retained."""

import math
import torch
from torch import nn
from torch.nn import functional as F

from .task import DURATIONS

KINDS = ("analytic", "hmm", "gru", "ssm", "cache")
WIDTH = 40


class ContentNetwork(nn.Module):
    def __init__(self, kind, law):
        super().__init__()
        if kind not in KINDS:
            raise ValueError("Unknown candidate")
        self.kind = kind
        self.intervention = None
        # The content head and symbol encoder are initialized before core-specific
        # parameters, with identical seeded bytes across model families.
        self.head = nn.Sequential(nn.Linear(WIDTH, 32), nn.Tanh(), nn.Linear(32, 4))
        self.symbol = nn.Linear(4, 4, bias=False)
        with torch.no_grad():
            self.symbol.weight.copy_(3 * torch.eye(4))
        self.register_buffer("Q", torch.tensor(law.Q.copy(), dtype=torch.float64))
        self.register_buffer("phase_prior", torch.tensor(law.phase_prior.copy(), dtype=torch.float64))
        self.register_buffer("durations", torch.tensor(DURATIONS, dtype=torch.float64))
        self.register_buffer("channel", .01 + .96 * torch.eye(4))
        # Every core receives the same public law and metadata. The strong
        # ordinary pool explicitly includes the exact same-Q HMM realization.
        self.register_buffer("metadata", torch.tensor([.30, .018]))
        if kind in ("analytic", "hmm"):
            self.log_scale = nn.Parameter(torch.tensor(math.log(.8), dtype=torch.float64))
        elif kind == "gru":
            self.gru = nn.GRUCell(9, WIDTH)
        elif kind == "ssm":
            self.ssm_factor = nn.Parameter(torch.randn(WIDTH, 4) * .02)
            self.log_decay = nn.Parameter(torch.linspace(-4., 0., WIDTH))
            self.event = nn.Linear(4, WIDTH)
            self.event_gate = nn.Parameter(torch.ones(WIDTH) * 3)

    def encoded(self, tokens):
        return self.symbol(F.one_hot(tokens, 4).float()).softmax(-1)

    def initial(self, initial):
        p = self.encoded(initial)
        if self.kind in ("analytic", "hmm"):
            return (self.phase_prior[None, None, :, None] * p.double()[..., None, :]).flatten(-2)
        if self.kind == "cache":
            return F.pad(p, (0, WIDTH - 4))
        if self.kind == "ssm":
            return self.event(p)
        zeros = p.new_zeros((*p.shape[:-1], WIDTH))
        return self.event_update(zeros, initial, 0)

    def transitions(self):
        if self.kind in ("analytic", "hmm"):
            return torch.matrix_exp(self.Q[None] * (self.durations * self.log_scale.exp())[:, None, None])
        if self.kind == "ssm":
            a = -(self.ssm_factor @ self.ssm_factor.T) - torch.diag(F.softplus(self.log_decay))
            return torch.matrix_exp(a[None] * self.durations.float()[:, None, None])
        return None

    def advance(self, state, index, matrices):
        if self.kind in ("analytic", "hmm", "ssm"):
            return self.project(torch.bmm(state, matrices[index]))
        if self.kind == "cache":
            age = state[..., 4:5] + self.durations[index].float()[:, None, None]
            return torch.cat((state[..., :4], age, state[..., 5:]), -1)
        batch = len(state)
        encoded = state.new_zeros(batch, 4, 4)
        kind = state.new_zeros(batch, 4, 2)
        meta = self.metadata[None, None].expand(batch, 4, -1)
        dt = self.durations[index].float()[:, None, None].expand(-1, 4, -1)
        features = torch.cat((encoded, kind, dt, meta), -1)
        return self.gru(features.flatten(0, 1), state.flatten(0, 1)).reshape_as(state)

    def event_update(self, state, tokens, event):
        shape = state.shape
        p = self.encoded(tokens)
        if self.kind in ("analytic", "hmm"):
            joint = state.reshape(*shape[:-1], 10, 4)
            if event == 0:  # public exact code WRITE, learned code basis
                return (joint.sum(-1, keepdim=True) * p.double()[..., None, :]).flatten(-2)
            emission = .01 + .96 * self.symbol.weight.softmax(-1)
            likelihood = F.embedding(tokens, emission.T).double()
            weighted = joint * likelihood[..., None, :]
            return self.project((weighted / weighted.sum((-1, -2), keepdim=True)).flatten(-2))
        if self.kind == "cache":
            return F.pad(p, (0, WIDTH - 4))
        if self.kind == "ssm":
            gate = self.event_gate.sigmoid()
            return state * (1 - gate) + self.event(p) * gate
        flag = F.one_hot(torch.full_like(tokens, event), 2).float()
        dt = p.new_zeros((*tokens.shape, 1))
        meta = self.metadata.expand(*tokens.shape, 2)
        features = torch.cat((p, flag, dt, meta), -1)
        return self.gru(features.flatten(0, -2), state.flatten(0, -2)).reshape(shape)

    def logits(self, state):
        return self.head(state.float())

    def project(self, state):
        if self.intervention is None:
            return state
        if self.kind not in ("analytic", "hmm") or self.intervention != "factorized":
            raise ValueError("Unsupported development intervention")
        joint = state.reshape(*state.shape[:-1], 10, 4)
        return (joint.sum(-1, keepdim=True) * joint.sum(-2, keepdim=True)).flatten(-2)


def replace(state, keys, value, enabled=None):
    mask = F.one_hot(keys.clamp_min(0), 4).to(state.dtype)
    if enabled is not None:
        mask = mask * enabled[:, None]
    return state * (1 - mask[..., None]) + value[:, None] * mask[..., None]


def rollout(model, batch, control, threshold, train=False, exploration=None):
    state = model.initial(batch["initial"])
    matrices = model.transitions()
    n, queries = batch["keys"].shape
    arange = torch.arange(n)
    losses, answers, actions, probabilities = [], [], [], []
    prior_probabilities, read_values, hypothetical = [], [], []
    for q in range(queries):
        write_key, write_value = batch["writes"][:, q].unbind(-1)
        old = state[arange, write_key.clamp_min(0)]
        written = model.event_update(old, write_value, 0)
        state = replace(state, write_key, written, write_key >= 0)
        state = model.advance(state, batch["duration_indices"][:, q], matrices)
        key = batch["keys"][:, q]
        selected = state[arange, key]
        before = model.logits(selected)
        p = before.softmax(-1)
        future = torch.stack([model.event_update(selected, torch.full((n,), y, dtype=torch.long), 1)
                              for y in range(4)], 1)
        after_logits = model.logits(future)
        expected = ((p @ model.channel) * after_logits.softmax(-1).max(-1).values).sum(-1)
        if exploration is not None:
            read = exploration[:, q]
        elif control == "value":
            read = expected.detach() - batch["fees"][:, q] > p.detach().max(-1).values
        else:
            read = batch["fees"][:, q] <= threshold
        # Runtime never indexes the unpurchased response. Offline training has
        # explicitly purchased the complete potential-observation collection.
        token = (batch["tokens"][:, q] if train else
                 torch.where(read, batch["tokens"][:, q], torch.zeros_like(key)))
        after = after_logits[arange, token]
        chosen = torch.where(read[:, None], after, before)
        state = replace(state, key, future[arange, token], read)
        if train:
            # Offline training collection purchases every potential observation
            # equally for every family; only chosen observations enter history.
            target = batch["targets"][:, q]
            losses.append(F.cross_entropy(chosen, target) + .25 * F.cross_entropy(after, target))
        answers.append(chosen.argmax(-1))
        actions.append(read)
        probabilities.append(chosen.softmax(-1))
        prior_probabilities.append(p.detach())
        read_values.append(expected.detach())
        hypothetical.append(after_logits.argmax(-1).detach())
    return (torch.stack(losses).mean() if losses else None,
            torch.stack(answers, 1), torch.stack(actions, 1), torch.stack(probabilities, 1),
            dict(prior=torch.stack(prior_probabilities, 1), read_value=torch.stack(read_values, 1),
                 hypothetical_answers=torch.stack(hypothetical, 1)))
