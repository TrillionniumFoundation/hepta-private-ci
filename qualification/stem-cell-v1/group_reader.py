"""Bounded query/candidate-conditioned reading of cached evidence vectors.

The query must encode the question together with the candidate answer. Facts
remain separate until attention; the first attention query already depends on
the question. Two logits classify candidate support, independent of answer names
or the number of candidates attached to a question. No symbolic solver is used.
"""
import math

import torch
from torch import nn
from torch.nn import functional as F


def _sigmoid(value):
    return (1 + (-value).exp()).reciprocal()


def _normalize(value):
    centered = value - value.mean(dim=-1, keepdim=True)
    return centered / ((centered * centered).mean(dim=-1, keepdim=True) + 1e-5).sqrt()


class Reader(nn.Module):
    """One small shared reader, with bounded state and explicit evidence attention."""

    def __init__(self, input_dim, hidden_dim=48, max_hops=8, max_facts=256):
        super().__init__()
        if (type(input_dim) is not int or not 2 <= input_dim <= 8192
                or not 8 <= hidden_dim <= 512 or not 1 <= max_hops <= 32
                or not 1 <= max_facts <= 1024):
            raise ValueError("bounded feature, state, evidence and hop dimensions required")
        self.input_dim, self.hidden_dim = input_dim, hidden_dim
        self.max_hops, self.max_facts, self.classes = max_hops, max_facts, 2
        self.fact_project = nn.Linear(input_dim, hidden_dim)
        self.question_project = nn.Linear(input_dim, hidden_dim)
        self.fact_key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.attention_query = nn.Linear(hidden_dim * 2, hidden_dim, bias=False)
        self.relation = nn.Linear(hidden_dim * 3, hidden_dim)
        self.relation_score = nn.Linear(hidden_dim, 1, bias=False)
        self.proposal = nn.Sequential(nn.Linear(hidden_dim * 3 + 4, hidden_dim), nn.GELU(),
                                      nn.Linear(hidden_dim, hidden_dim))
        self.update_gate = nn.Linear(hidden_dim * 3 + 4, hidden_dim)
        self.head = nn.Sequential(nn.Linear(hidden_dim * 3 + 1, hidden_dim), nn.GELU(),
                                  nn.Linear(hidden_dim, 2))

    def _validate(self, facts, query, state, feedback, mask):
        if (facts.ndim != 3 or not 1 <= facts.shape[0] <= 4096
                or not 1 <= facts.shape[1] <= self.max_facts or facts.shape[2] != self.input_dim
                or query.shape != (facts.shape[0], self.input_dim)):
            raise ValueError("aligned bounded fact and query/candidate vectors required")
        batch, count, _ = facts.shape
        if state is not None and state.shape != (batch, self.hidden_dim):
            raise ValueError("wrong reader state dimensions")
        if feedback is not None and feedback.shape != (batch, 4):
            raise ValueError("four public status features required")
        if mask is not None and (mask.shape != (batch, count) or mask.dtype != torch.bool):
            raise ValueError("boolean evidence mask required")

    def step_with_attention(self, facts, query, state=None, feedback=None, mask=None):
        """Return state, binary logits, and differentiable per-fact attention.

        Empty evidence is represented by a fully false mask, retaining one or
        more padding rows. It yields exactly zero attention and evidence context.
        """
        self._validate(facts, query, state, feedback, mask)
        batch, count, _ = facts.shape
        question = _sigmoid(self.question_project(_normalize(query))) * 2 - 1
        evidence = F.gelu(self.fact_project(_normalize(facts)))
        state = question if state is None else state
        feedback = facts.new_zeros(batch, 4) if feedback is None else feedback
        key = self.fact_key(evidence)
        attention_query = self.attention_query(torch.cat((question, state), dim=-1))
        scores = (key * attention_query.unsqueeze(1)).sum(-1) / math.sqrt(self.hidden_dim)
        question_rows = question.unsqueeze(1).expand(-1, count, -1)
        relations = F.gelu(self.relation(torch.cat((evidence, question_rows,
                                                    evidence * question_rows), dim=-1)))
        scores = scores + self.relation_score(relations).squeeze(-1)
        weights = torch.ones_like(scores) if mask is None else mask.to(facts.dtype)
        scores = scores.masked_fill(weights.eq(0), -10_000.)
        attention = scores.softmax(-1) * weights
        attention = attention / (attention.sum(-1, keepdim=True) + 1e-9)
        context = (relations * attention.unsqueeze(-1)).sum(1)
        update = torch.cat((question, state, context, feedback), dim=-1)
        gate = _sigmoid(self.update_gate(update))
        proposal = _sigmoid(self.proposal(update)) * 2 - 1
        state = (torch.ones_like(gate) - gate) * state + gate * proposal
        present = weights.sum(-1, keepdim=True).clamp(max=1)
        logits = self.head(torch.cat((question, state, context, present), dim=-1))
        return state, logits, attention

    def step(self, facts, query, state=None, feedback=None, mask=None):
        state, logits, _ = self.step_with_attention(facts, query, state, feedback, mask)
        return state, logits

    def forward(self, facts, query, steps=3, mask=None, feedback=None, state=None,
                return_attention=False, reset_state=False):
        if type(steps) is not int or not 1 <= steps <= self.max_hops:
            raise ValueError("reader hop limit exceeded")
        states, logits_trace, attentions = [], [], []
        for _ in range(steps):
            state, logits, attention = self.step_with_attention(
                facts, query, None if reset_state else state, feedback, mask)
            states.append(state)
            logits_trace.append(logits)
            attentions.append(attention)
        if return_attention:
            return dict(state=state, logits=logits, states=states,
                        step_logits=logits_trace, attentions=attentions)
        return logits
