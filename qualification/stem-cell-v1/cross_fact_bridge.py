"""Research-only matched 4H^2 fact-to-fact vs fact-local Reader adapter.

The six public TokenReader input tensors remain unchanged. A new fact-to-fact
communication path is compared to an equal-parameter local noncommunication
control. No labels, source IDs, or evaluator judgments enter inference.
"""
import math

import torch
from torch import nn
from torch.nn import functional as F

from token_reader import TokenReader, _mean


class FactInteractionBlock(nn.Module):
    """Four bias-free HxH matrices in both arms; only one mixes fact slots."""

    def __init__(self, width: int, mode: str):
        super().__init__()
        if type(width) is not int or not 8 <= width <= 512 or mode not in ('cross_fact', 'local'):
            raise ValueError('bounded width and registered matched mode required')
        self.width = width
        self.mode = mode
        self.a = nn.Linear(width, width, bias=False)
        self.b = nn.Linear(width, width, bias=False)
        self.c = nn.Linear(width, width, bias=False)
        self.d = nn.Linear(width, width, bias=False)

    def forward(self, facts: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
        if (facts.ndim != 3 or not 1 <= facts.shape[0] <= 4096
                or not 1 <= facts.shape[1] <= 1024 or facts.shape[-1] != self.width
                or valid.shape != facts.shape[:2]
                or valid.dtype != torch.bool or not valid.any(-1).all()
                or not torch.isfinite(facts).all()):
            raise ValueError('valid bounded fact vectors and nonempty masks required')
        if facts.shape[0] * facts.shape[1] * facts.shape[1] > 2_000_000:
            raise ValueError('bounded fact attention work required')
        if self.mode == 'cross_fact':
            queries, keys, values = self.a(facts), self.b(facts), self.c(facts)
            scores = torch.bmm(queries, keys.transpose(1, 2)) / math.sqrt(self.width)
            scores = scores.masked_fill(~valid[:, None, :], -10000.)
            attention = scores.softmax(-1) * valid[:, None, :].to(scores.dtype)
            attention = attention / attention.sum(-1, keepdim=True).clamp_min(1e-9)
            output = self.d(torch.bmm(attention, values))
        else:
            output = self.d(F.gelu(self.c(F.gelu(self.b(F.gelu(self.a(facts)))))))
        return (output / math.sqrt(self.width)) * valid.unsqueeze(-1)


class CrossFactTokenReader(TokenReader):
    """Existing TokenReader with one optional cross-fact bridge in preparation.

    Retain the exact public six-tensor forward ABI. Both arms carry 4H^2
    extra parameters and execute the same base Reader with one adapter call.
    """

    def __init__(self, input_dim: int, hidden_dim: int = 32, *, mode: str = 'cross_fact', **kwargs):
        super().__init__(input_dim, hidden_dim=hidden_dim, **kwargs)
        self.fact_block = FactInteractionBlock(hidden_dim, mode)
        self.fact_block_mode = mode

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        prepared = super().prepare(facts, question, candidate, fact_mask,
                                   question_mask, candidate_mask)
        token_mask = prepared['fact_mask']
        valid = token_mask.any(-1)
        summaries = _mean(prepared['relations'], token_mask)
        delta = self.fact_block(summaries, valid)
        # Do not allow modifications to padded tokens to leak into downstream
        # keys, fact scores or recurrent workspace state.
        prepared['relations'] = prepared['relations'] + delta[:, :, None, :] * token_mask.unsqueeze(-1)
        prepared['token_keys'] = self.token_key(prepared['relations'])
        return prepared


def matched_reader_pair(input_dim=8, hidden_dim=32, *, seed=41):
    """Same initial base Reader weights and exact equal parameter counts."""
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('bounded seed required')
    # fork_rng preserves a caller's global RNG state, including after failure.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        cross = CrossFactTokenReader(input_dim, hidden_dim, mode='cross_fact')
        torch.manual_seed(seed)
        local = CrossFactTokenReader(input_dim, hidden_dim, mode='local')
    if sum(p.numel() for p in cross.parameters()) != sum(p.numel() for p in local.parameters()):
        raise RuntimeError('unequal matched Reader parameters')
    for key, tensor in cross.state_dict().items():
        if not key.startswith('fact_block.'):
            if not torch.equal(tensor, local.state_dict()[key]):
                raise RuntimeError('base Reader initial weights diverged')
    return cross, local
