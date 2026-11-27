"""V8 research-only cross-fact token matching; no annotation, label or authority input.

Opt-in experimental Reader. Frozen V7/V6 classes are not modified. A zero-initialized
output projection makes a newly constructed reader exactly match the base TokenReader.
A token-key desynchronization intervention is a diagnostic, NOT a trained competitor.
"""
import math

import torch
from torch import nn

from token_reader import TokenReader, _attention


class TokenMatchBridge(nn.Module):
    """Use different fact token endpoints, not pooled fact means, for messages."""
    def __init__(self, hidden_dim=32):
        super().__init__()
        if type(hidden_dim) is not int or not 8 <= hidden_dim <= 512:
            raise ValueError("bounded integer hidden dimension required")
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim, bias=False)
        nn.init.zeros_(self.output.weight)

    def forward(self, relations, token_mask, *, desync_keys=False):
        if (relations.ndim != 4 or token_mask.shape != relations.shape[:3]
                or token_mask.dtype != torch.bool or relations.device.type != "cpu"
                or token_mask.device != relations.device or relations.shape[-1] != self.query.in_features
                or not torch.isfinite(relations).all()):
            raise ValueError("finite aligned CPU relation tokens and boolean masks required")
        if type(desync_keys) is not bool:
            raise ValueError("explicit boolean intervention required")
        batch, facts, tokens, dim = relations.shape
        count = facts * tokens
        if batch == 0 or facts < 1 or tokens < 1 or batch * count * count > 2_000_000:
            raise ValueError("bounded cross-fact attention geometry required")
        flat = relations.reshape(batch, count, dim)
        present = token_mask.reshape(batch, count)
        identity = torch.arange(facts).repeat_interleave(tokens)
        cross_fact = identity[:, None] != identity[None, :]
        admissible = (present[:, :, None] & present[:, None, :]
                      & cross_fact[None, :, :])
        q = self.query(flat)
        k = self.key(flat)
        if desync_keys:
            # Break key/value correspondence only, preserving work, masks and values.
            k = k.roll(1, dims=1)
        scores = torch.matmul(q, k.transpose(1, 2)) / math.sqrt(dim)
        weights = _attention(scores, admissible)
        message = self.output(weights @ self.value(flat))
        message = message * present.unsqueeze(-1).to(message.dtype)
        return relations + message.reshape_as(relations)


class EndpointReader(TokenReader):
    """Same 38,466 base parameters and 4,096 added parameters as V6 BridgeReader."""
    def __init__(self, input_dim=384, hidden_dim=32, max_hops=8, *, residual_seed=0):
        super().__init__(input_dim, hidden_dim, max_hops=max_hops)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(residual_seed)
            self.token_bridge = TokenMatchBridge(hidden_dim)
        self.reader_arm = "endpoint_v8"
        self.desync_keys = False

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        prepared = super().prepare(facts, question, candidate, fact_mask,
                                   question_mask, candidate_mask)
        relations = self.token_bridge(prepared["relations"], prepared["fact_mask"],
                                      desync_keys=self.desync_keys)
        return {**prepared, "relations": relations, "token_keys": self.token_key(relations)}


def build_endpoint(seed):
    if type(seed) is not int or seed < 0:
        raise ValueError("nonnegative integer seed required")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = EndpointReader(residual_seed=seed ^ 0x6B12)
    base = 384 * 32 + 25 * 32**2 + 18 * 32 + 2
    if sum(p.numel() for p in model.parameters()) != base + 4 * 32**2 or base + 4 * 32**2 != 42562:
        raise ValueError("registered endpoint model parameter count changed")
    return model
