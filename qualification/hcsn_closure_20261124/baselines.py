"""Small conventional baselines with explicit causal streaming state.

Fixed initial states, discretization, surrogate derivatives and KV growth are
reported differences, not claims of functional capacity equality with HCSN.
"""

from dataclasses import dataclass
import math
from types import SimpleNamespace

import torch
from torch import nn

from qualification.hcsn_smallnet_20261124.data import probability_metrics


@dataclass
class BaselineState:
    tensors: tuple
    step: int


class GRUClassifier(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.config = SimpleNamespace(kind="GRU", width=width)
        self.core = nn.GRU(6, width)
        self.readout = nn.Linear(width, 2)

    def initial_state(self, batch, initial_margin=None):
        return BaselineState((self.readout.weight.new_zeros(1, batch, self.config.width),), 0)

    def forward(self, x, state=None, return_features=False):
        state = self.initial_state(x.shape[1]) if state is None else state
        features, hidden = self.core(x, state.tensors[0])
        result = self.readout(features)
        return (result, features, BaselineState((hidden,), state.step+len(x))) if return_features else result


class SurrogateSpike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, gap):
        ctx.save_for_backward(gap)
        return (gap >= 0).to(gap)

    @staticmethod
    def backward(ctx, gradient):
        (gap,) = ctx.saved_tensors
        return gradient/(1+5*gap.abs()).square()


class LIFClassifier(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.config = SimpleNamespace(kind="surrogate_LIF", width=width)
        self.input = nn.Linear(6, width, bias=False)
        self.recurrent = nn.Linear(width, width, bias=False)
        self.readout = nn.Linear(width, 2)

    def initial_state(self, batch, initial_margin=None):
        zero = self.readout.weight.new_zeros(batch, self.config.width)
        return BaselineState((zero.clone(), zero.clone(), zero.clone()), 0)

    def forward(self, x, state=None, return_features=False):
        state = self.initial_state(x.shape[1]) if state is None else state
        membrane, spike, trace = state.tensors
        features = []
        for value in x:
            membrane = .9*membrane+self.input(value)+self.recurrent(spike)
            spike = SurrogateSpike.apply(membrane-1)
            membrane = membrane-spike.detach()
            trace = .8*trace+spike
            features.append(trace)
        features = torch.stack(features); result = self.readout(features)
        return (result, features, BaselineState((membrane, spike, trace), state.step+len(x))) if return_features else result


class CausalTransformer(nn.Module):
    """One pre-LN block, one head, FF=2d, dropout=0, sinusoidal positions."""
    def __init__(self, width):
        super().__init__()
        self.config = SimpleNamespace(kind="causal_Transformer", width=width)
        self.input = nn.Linear(6, width)
        self.norm1 = nn.LayerNorm(width)
        self.qkv = nn.Linear(width, 3*width)
        self.output = nn.Linear(width, width)
        self.norm2 = nn.LayerNorm(width)
        self.ff = nn.Sequential(nn.Linear(width, 2*width), nn.GELU(), nn.Linear(2*width, width))
        self.readout = nn.Linear(width, 2)

    def initial_state(self, batch, initial_margin=None):
        empty = self.readout.weight.new_zeros(batch, 0, self.config.width)
        return BaselineState((empty.clone(), empty.clone()), 0)

    def forward(self, x, state=None, return_features=False):
        state = self.initial_state(x.shape[1]) if state is None else state
        width = self.config.width
        if state.tensors[0].shape[1] != state.step or state.tensors[1].shape != state.tensors[0].shape:
            raise ValueError("complete untruncated KV prefix required")
        positions = torch.arange(state.step, state.step+len(x), device=x.device, dtype=x.dtype)
        frequency = torch.exp(torch.arange(0, width, 2, device=x.device, dtype=x.dtype)*(-math.log(10000)/width))
        positional = x.new_zeros(len(x), width)
        positional[:, 0::2] = torch.sin(positions[:, None]*frequency)
        positional[:, 1::2] = torch.cos(positions[:, None]*frequency[:width//2])
        features = self.input(x)+positional[:, None]
        query, key, value = (v.transpose(0, 1) for v in self.qkv(self.norm1(features)).chunk(3, -1))
        keys, values = torch.cat((state.tensors[0], key), 1), torch.cat((state.tensors[1], value), 1)
        attention = query@keys.transpose(-1, -2)/math.sqrt(width)
        future = torch.arange(keys.shape[1], device=x.device)[None, :] > positions.long()[:, None]
        attention = attention.masked_fill(future, float("-inf")).softmax(-1)
        features = features+self.output((attention@values).transpose(0, 1))
        features = features+self.ff(self.norm2(features))
        result = self.readout(features)
        return (result, features, BaselineState((keys, values), state.step+len(x))) if return_features else result


def make_model(slot):
    models = {"GRU": GRUClassifier, "surrogate_LIF": LIFClassifier,
              "causal_Transformer": CausalTransformer}
    return models[slot["kind"]](slot["width"])


def parameter_accounting(model):
    return {"total_parameters": sum(p.numel() for p in model.parameters()),
            "requires_grad_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "architecture": vars(model.config), "initial_state": "zero; physical initial_margin is unused",
            "lif_rule": "leak=.9; threshold/reset=1; trace=.8; surrogate=1/(1+5*abs(gap))^2; reset spike detached" if model.config.kind == "surrogate_LIF" else None,
            "scope": "All parameter tensors present; not an equality of functional capacity or training cost."}


@torch.no_grad()
def evaluate(model, batch, *, chunk=16, include_features=False):
    logits, features, state_bytes, last_step = [], [], 0, 0
    for start in range(0, len(batch.y), chunk):
        part = batch.select(torch.arange(start, min(start+chunk, len(batch.y))))
        out, latent, state = model(part.x, return_features=True)
        logits.append(out.cpu())
        if include_features:
            features.append(latent[-1].cpu())
        state_bytes = max(state_bytes, sum(t.numel()*t.element_size() for t in state.tensors))
        last_step = max(last_step, state.step)
    logits = torch.cat(logits, 1)
    if not bool(torch.isfinite(logits).all()):
        raise FloatingPointError("nonfinite baseline logits")
    result = probability_metrics(logits, batch)
    result.update(maximum_chunk_state_tensor_bytes=state_bytes, recorded_prefix_length=last_step,
                  state_bytes_scope="all persistent hidden/trace/KV tensors; excludes weights, transient attention and AD tape",
                  state_growth="linear in prefix length (2*batch*length*width floats)" if model.config.kind == "causal_Transformer" else "constant in prefix length")
    return result, logits, torch.cat(features) if include_features else None


@torch.no_grad()
def causal_streaming_control(model, x):
    full, _, complete = model(x, return_features=True)
    state, pieces = None, []
    for row in x:
        value, _, state = model(row[None], state=state, return_features=True)
        pieces.append(value)
    changed = x.clone(); changed[len(x)//2:] += .7
    future = model(changed)
    streamed = torch.cat(pieces)
    return {"stream_equivalent": bool(torch.allclose(full, streamed, atol=2e-6, rtol=2e-6)),
            "max_stream_error": float((full-streamed).abs().max()),
            "future_invariant": bool(torch.equal(full[:len(x)//2], future[:len(x)//2])),
            "state_step": state.step,
            "state_bytes": sum(t.numel()*t.element_size() for t in complete.tensors),
            "state_shapes": [list(t.shape) for t in complete.tensors]}
