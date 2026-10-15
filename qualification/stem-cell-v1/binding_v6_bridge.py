"""Research-only, equal-parameter fact-to-fact bridge on the existing V5 Reader.

The frozen Granite token cache and original TokenReader are not modified.
All three arms take exactly the same six detached public feature tensors.
The additional parameters are precisely 4 * hidden_dim**2; there is no
annotation, label, world ID or support index in the inference path.
"""
import math

import torch
from torch import nn
from torch.nn import functional as F

from token_reader import TokenReader


ARMS = ("cross_fact", "global_pool", "local")


class FactBridgeReader(TokenReader):
    """Bridge fact representations before the pre-existing recurrent readout.

    cross_fact: content-addressable fact-to-fact attention.
    global_pool: same four matrices with an unselective global summary.
    local: same four matrices applied independently to each fact.

    A fixed small residual gain prevents a fresh bridge from dominating the
    pretrained, already-frozen Encoder representation at initialization.
    """

    def __init__(self, input_dim=384, hidden_dim=32, *, bridge_arm="cross_fact", **kwargs):
        if bridge_arm not in ARMS:
            raise ValueError("registered bridge arm required")
        super().__init__(input_dim, hidden_dim, **kwargs)
        self.bridge_arm = bridge_arm
        self.bridge_q = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.bridge_k = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.bridge_v = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.bridge_o = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.bridge_gain = 0.25

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        prepared = super().prepare(facts, question, candidate, fact_mask,
                                   question_mask, candidate_mask)
        relations, mask = prepared["relations"], prepared["fact_mask"]
        if relations.shape[:3] != mask.shape:
            raise ValueError("unaligned post-Encoder fact tokens")
        valid = mask.any(dim=-1)
        lengths = mask.sum(dim=-1, keepdim=True).clamp(min=1)
        fact_means = (relations * mask.unsqueeze(-1)).sum(dim=2) / lengths
        q = self.bridge_q(fact_means)
        k = self.bridge_k(fact_means)
        v = self.bridge_v(fact_means)
        if self.bridge_arm == "cross_fact":
            scores = q @ k.transpose(1, 2) / math.sqrt(self.hidden_dim)
            scores = scores.masked_fill(~valid[:, None, :], -1e4)
            weights = scores.softmax(-1) * valid[:, None, :].to(scores.dtype)
            weights = weights / weights.sum(-1, keepdim=True).clamp(min=1e-9)
            mixed = weights @ v
        elif self.bridge_arm == "global_pool":
            global_value = (v * valid.unsqueeze(-1)).sum(1, keepdim=True) / (
                valid.sum(1, keepdim=True).unsqueeze(-1).clamp(min=1))
            confidence = torch.sigmoid((q * k).sum(-1, keepdim=True) /
                                       math.sqrt(self.hidden_dim))
            mixed = global_value * confidence
        else:
            mixed = F.gelu(v + q * k)
        delta = torch.tanh(self.bridge_o(mixed)) * (self.bridge_gain * valid.unsqueeze(-1))
        out = relations + delta.unsqueeze(2)
        return {**prepared, "relations": out, "token_keys": self.token_key(out)}


def equal_parameter_arms(input_dim=384, hidden_dim=32, *, seed=41, **kwargs):
    """Produce independently stored arms with exactly identical initial tensors.

    Caller owns all training and costs; initial bytes only are shared.
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("bounded integer initialization seed required")
    result = {}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        origin = FactBridgeReader(input_dim, hidden_dim, bridge_arm=ARMS[0], **kwargs)
        frozen_initial = {name: value.detach().clone()
                          for name, value in origin.state_dict().items()}
        for arm in ARMS:
            model = FactBridgeReader(input_dim, hidden_dim, bridge_arm=arm, **kwargs)
            model.load_state_dict(frozen_initial, strict=True)
            result[arm] = model.eval().requires_grad_(False)
    counts = {arm: sum(p.numel() for p in model.parameters()) for arm, model in result.items()}
    if len(set(counts.values())) != 1 or counts[ARMS[0]] != sum(
        p.numel() for p in origin.parameters()):
        raise RuntimeError("bridge control has an unequal parameter budget")
    if counts[ARMS[0]] - sum(p.numel() for p in TokenReader(input_dim, hidden_dim, **kwargs).parameters()) != 4 * hidden_dim**2:
        raise RuntimeError("bridge parameter budget must match the registered four matrices")
    return result
