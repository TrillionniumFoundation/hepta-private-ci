"""A/B/C from scratch; all arms receive the complete binary conditional law."""
import torch
from torch import nn
from torch.func import functional_call


def inputs(v, w):
    a, b = v[..., w['left']], v[..., w['right']]
    broad = lambda x: x.expand_as(a)
    f = torch.stack((a, b, broad(w['p']), broad(w['risk']),
                     broad(w['c']), torch.full_like(a, w['gamma'])), -1)
    skip = w['c'] + w['gamma'] * (w['p']*a + (1-w['p'])*b)
    return f, skip


class StateStem(nn.Module):
    """Shared nonlinear state-evolution block, 65 weights; B and C are identical."""
    def __init__(self, seed=11, width=8):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.net = nn.Sequential(nn.Linear(6, width), nn.Tanh(), nn.Linear(width, 1)).double()
            with torch.no_grad():
                self.net[2].weight.mul_(0.1)
                self.net[2].bias.zero_()

    def forward(self, v, w):
        f, skip = inputs(v, w)
        return skip + self.net(f).squeeze(-1)


class TransformerStem(nn.Module):
    """One full self-attention/FFN block, no positional state IDs or pretrained weights."""
    def __init__(self, seed=11):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.embed = nn.Linear(6, 8)
            self.block = nn.TransformerEncoderLayer(8, 2, dim_feedforward=16,
                                                   dropout=0.0, batch_first=True,
                                                   activation='gelu', norm_first=True)
            self.out = nn.Linear(8, 1)
            with torch.no_grad():
                self.out.weight.mul_(0.1)
                self.out.bias.zero_()
        self.double()

    def forward(self, v, w):
        f, skip = inputs(v, w)
        return skip + self.out(self.block(self.embed(f))).squeeze(-1)


def vector(model):
    return torch.cat([p.detach().reshape(-1) for p in model.parameters()]).numpy().copy()


def assign(model, values):
    offset = 0
    with torch.no_grad():
        for p in model.parameters():
            part = torch.as_tensor(values[offset:offset+p.numel()], dtype=p.dtype)
            p.copy_(part.reshape(p.shape))
            offset += p.numel()
    if offset != len(values):
        raise ValueError("parameter vector length mismatch")


def call_vector(model, theta, v, world):
    pars, offset = {}, 0
    for name, p in model.named_parameters():
        pars[name] = theta[offset:offset+p.numel()].reshape(p.shape)
        offset += p.numel()
    return functional_call(model, pars, (v, world))
