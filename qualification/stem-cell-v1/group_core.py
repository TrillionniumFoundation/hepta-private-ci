"""Small trainable Group state over cached, frozen token features.

This module never encodes text or solves a task symbolically. Every candidate is
the readout of learned attention and recurrent state. A valid mask marks tokens
that exist; verifier feedback contains status categories, never the answer.
"""
import math

import torch
from torch import nn


class Core(nn.Module):
    """Shared bounded recurrent core; individual Cell readouts may wrap it."""

    def __init__(self, input_dim, hidden_dim=32, classes=8):
        super().__init__()
        if not 1 <= input_dim <= 8192 or not 4 <= hidden_dim <= 512 or not 2 <= classes <= 256:
            raise ValueError("bounded feature, state and class dimensions required")
        self.input_dim, self.hidden_dim, self.classes = input_dim, hidden_dim, classes
        self.project = nn.Linear(input_dim, hidden_dim)
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.start = nn.Parameter(torch.zeros(hidden_dim))
        self.update_gate = nn.Linear(hidden_dim * 2 + 4, hidden_dim)
        self.proposal = nn.Sequential(nn.Linear(hidden_dim * 2 + 4, hidden_dim), nn.GELU(),
                                      nn.Linear(hidden_dim, hidden_dim))
        self.head = nn.Linear(hidden_dim, classes)

    @staticmethod
    def _sigmoid(value):
        # Explicit arithmetic remains visible to the eager operator work meter.
        return (1 + (-value).exp()).reciprocal()

    def step(self, tokens, state=None, feedback=None, mask=None):
        """Consume [batch, tokens, features], return ([batch, state], logits)."""
        if tokens.ndim != 3 or tokens.shape[2] != self.input_dim or not 1 <= tokens.shape[1] <= 1024:
            raise ValueError("bounded batch of token features required")
        batch, length, _ = tokens.shape
        if state is None:
            state = (self._sigmoid(self.start) * 2 - 1).expand(batch, -1)
        if state.shape != (batch, self.hidden_dim):
            raise ValueError("state has wrong dimensions")
        if feedback is None:
            feedback = tokens.new_zeros(batch, 4)
        if feedback.shape != (batch, 4):
            raise ValueError("four non-answer verifier status features required")
        centered = tokens - tokens.mean(dim=-1, keepdim=True)
        normalized = centered / ((centered * centered).mean(dim=-1, keepdim=True) + 1e-5).sqrt()
        keys = nn.functional.gelu(self.project(normalized))
        scores = torch.einsum("bth,bh->bt", keys, self.query(state)) / math.sqrt(self.hidden_dim)
        if mask is not None:
            if mask.shape != (batch, length) or mask.dtype != torch.bool or not mask.any(dim=1).all():
                raise ValueError("mask must retain at least one token per example")
            scores = scores.masked_fill(mask.eq(False), -torch.inf)
        context = torch.einsum("bt,bth->bh", scores.softmax(dim=1), keys)
        update_input = torch.cat((context, state, feedback), dim=-1)
        gate = self._sigmoid(self.update_gate(update_input))
        candidate = self._sigmoid(self.proposal(update_input)) * 2 - 1
        state = (torch.ones_like(gate) - gate) * state + gate * candidate
        return state, self.head(state)

    def forward(self, tokens, steps=1, mask=None, feedback=None, reset_state=False):
        if type(steps) is not int or not 1 <= steps <= 64:
            raise ValueError("bounded recurrence depth required")
        state = None
        for _ in range(steps):
            state, logits = self.step(tokens, None if reset_state else state, feedback, mask)
        return logits
