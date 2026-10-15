"""Small bounded Reader over frozen, distinct evidence/question/candidate tokens.

The pooled control uses exactly the same parameters, replacing every token group
by its masked mean before interaction. Neither mode sees labels or annotations.
"""
import math

import torch
from torch import nn
from torch.nn import functional as F


def _mean(value, mask):
    weights = mask.to(value.dtype).unsqueeze(-1)
    return (value * weights).sum(-2) / weights.sum(-2).clamp(min=1)


def _attention(scores, mask):
    weights = mask.to(scores.dtype)
    result = scores.masked_fill(~mask, -10000.).softmax(-1) * weights
    return result / result.sum(-1, keepdim=True).clamp(min=1e-9)


def _normalize(value):
    return F.layer_norm(value, (value.shape[-1],))


def _sigmoid(value):
    # FP32 tails are already saturated; bounding exp also keeps backward finite.
    return (1 + (-value.clamp(min=-30, max=30)).exp()).reciprocal()


def _tanh(value):
    return _sigmoid(value * 2) * 2 - 1


class TokenReader(nn.Module):
    """Low rank token alignment, evidence attention, and a bounded recurrent state."""

    def __init__(self, input_dim, hidden_dim=32, max_hops=8, max_facts=256,
                 max_tokens=1024, interaction="token"):
        super().__init__()
        if (type(input_dim) is not int or not 2 <= input_dim <= 8192
                or not 8 <= hidden_dim <= 512 or not 1 <= max_hops <= 32
                or not 1 <= max_facts <= 1024 or not 1 <= max_tokens <= 4096
                or interaction not in ("token", "pooled")):
            raise ValueError("bounded token Reader dimensions and known interaction required")
        self.input_dim, self.hidden_dim = input_dim, hidden_dim
        self.max_hops, self.max_facts, self.max_tokens = max_hops, max_facts, max_tokens
        self.interaction, self.classes = interaction, 2
        self.project = nn.Linear(input_dim, hidden_dim, bias=False)
        self.query = nn.Linear(hidden_dim * 4, hidden_dim)
        self.relation = nn.Linear(hidden_dim * 8, hidden_dim)
        self.token_score = nn.Linear(hidden_dim, 1, bias=False)
        self.token_key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.fact_score = nn.Linear(hidden_dim, 1, bias=False)
        self.fact_key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.state_query = nn.Linear(hidden_dim * 2, hidden_dim, bias=False)
        self.proposal = nn.Linear(hidden_dim * 3 + 4, hidden_dim)
        self.update_gate = nn.Linear(hidden_dim * 3 + 4, hidden_dim)
        self.head = nn.Sequential(nn.Linear(hidden_dim * 3 + 1, hidden_dim), nn.GELU(),
                                  nn.Linear(hidden_dim, 2))

    def _validate(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        if (facts.ndim != 4 or not 1 <= facts.shape[0] <= 4096
                or not 1 <= facts.shape[1] <= self.max_facts
                or not 1 <= facts.shape[2] <= self.max_tokens or facts.shape[-1] != self.input_dim):
            raise ValueError("bounded fact-token tensor required")
        batch = facts.shape[0]
        for value, mask in ((facts, fact_mask), (question, question_mask), (candidate, candidate_mask)):
            if (value.shape[0] != batch or value.shape[-1] != self.input_dim
                    or mask.shape != value.shape[:-1] or mask.dtype != torch.bool
                    or value.device.type != "cpu" or mask.device != value.device):
                raise ValueError("aligned CPU tokens and boolean masks required")
        if (question.ndim != 3 or candidate.ndim != 3
                or not 1 <= question.shape[1] <= self.max_tokens
                or not 1 <= candidate.shape[1] <= self.max_tokens):
            raise ValueError("bounded distinct question and candidate tokens required")
        if (facts.shape[0] * facts.shape[1] * facts.shape[2]
                * (question.shape[1] + candidate.shape[1]) > 64_000_000):
            raise ValueError("alignment tensor limit exceeded; reduce batch size")

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        """Project and align once; recursive hops reuse the prepared representation."""
        self._validate(facts, question, candidate, fact_mask, question_mask, candidate_mask)
        evidence, qtokens, atokens = (self.project(_normalize(value))
                                     for value in (facts, question, candidate))
        if self.interaction == "pooled":
            evidence, qtokens, atokens = (_mean(evidence, fact_mask).unsqueeze(-2),
                _mean(qtokens, question_mask).unsqueeze(-2), _mean(atokens, candidate_mask).unsqueeze(-2))
            fact_mask, question_mask, candidate_mask = (fact_mask.any(-1, keepdim=True),
                question_mask.any(-1, keepdim=True), candidate_mask.any(-1, keepdim=True))
        qmean, amean = _mean(qtokens, question_mask), _mean(atokens, candidate_mask)
        query = _tanh(self.query(torch.cat((qmean, amean, qmean * amean, qmean - amean), -1)))
        aligned = []
        for tokens, mask in ((qtokens, question_mask), (atokens, candidate_mask)):
            scores = torch.einsum("bftd,bqd->bftq", evidence, tokens) / math.sqrt(self.hidden_dim)
            attention = _attention(scores, mask[:, None, None, :].expand_as(scores))
            aligned.append(torch.einsum("bftq,bqd->bftd", attention, tokens))
        qalign, aalign = aligned
        relations = F.gelu(self.relation(torch.cat((evidence, qalign, aalign,
            evidence * qalign, evidence * aalign, qalign * aalign,
            evidence - qalign, evidence - aalign), -1)))
        return dict(relations=relations, query=query, fact_mask=fact_mask,
                    token_keys=self.token_key(relations))

    def step_prepared(self, prepared, state=None, feedback=None):
        relations, query, mask = (prepared[key] for key in ("relations", "query", "fact_mask"))
        batch = query.shape[0]
        state = query if state is None else state
        feedback = query.new_zeros(batch, 4) if feedback is None else feedback
        if (state.shape != (batch, self.hidden_dim) or feedback.shape != (batch, 4)
                or state.device != query.device or feedback.device != query.device):
            raise ValueError("aligned bounded state and four public feedback features required")
        if (not torch.isfinite(state).all() or state.abs().max().item() > 1.000001
                or not torch.isfinite(feedback).all()):
            raise ValueError("Reader state must remain finite inside [-1,1]")
        lookup = self.state_query(torch.cat((query, state), -1))
        token_scores = self.token_score(relations).squeeze(-1)
        token_scores = token_scores + (prepared["token_keys"] * lookup[:, None, None]).sum(-1) / math.sqrt(self.hidden_dim)
        token_attention = _attention(token_scores, mask)
        facts = (relations * token_attention.unsqueeze(-1)).sum(-2)
        fact_scores = self.fact_score(facts).squeeze(-1)
        fact_scores = fact_scores + (self.fact_key(facts) * lookup[:, None]).sum(-1) / math.sqrt(self.hidden_dim)
        attention = _attention(fact_scores, mask.any(-1))
        context = (facts * attention.unsqueeze(-1)).sum(1)
        update = torch.cat((query, state, context, feedback), -1)
        gate = _sigmoid(self.update_gate(update))
        state = (torch.ones_like(gate) - gate) * state + gate * _tanh(self.proposal(update))
        present = mask.any(-1).any(-1).to(query.dtype).unsqueeze(-1)
        logits = self.head(torch.cat((query, state, context, present), -1))
        return state, logits, attention, token_attention

    def step_with_attention(self, facts, question, candidate, fact_mask, question_mask,
                            candidate_mask, state=None, feedback=None):
        state, logits, attention, _ = self.step_prepared(self.prepare(
            facts, question, candidate, fact_mask, question_mask, candidate_mask), state, feedback)
        return state, logits, attention

    def step(self, facts, question, candidate, fact_mask, question_mask, candidate_mask,
             state=None, feedback=None):
        state, logits, _ = self.step_with_attention(facts, question, candidate,
            fact_mask, question_mask, candidate_mask, state, feedback)
        return state, logits

    def forward(self, facts, question, candidate, fact_mask, question_mask, candidate_mask,
                steps=1, state=None, feedback=None, return_attention=False, reset_state=False):
        if type(steps) is not int or not 1 <= steps <= self.max_hops:
            raise ValueError("bounded Reader depth required")
        prepared = self.prepare(facts, question, candidate, fact_mask, question_mask, candidate_mask)
        states, logits_trace, attentions, token_attentions = [], [], [], []
        for _ in range(steps):
            state, logits, attention, tokens = self.step_prepared(
                prepared, None if reset_state else state, feedback)
            states.append(state)
            logits_trace.append(logits)
            attentions.append(attention)
            token_attentions.append(tokens)
        if return_attention:
            return dict(state=state, logits=logits, states=states, step_logits=logits_trace,
                        attentions=attentions, token_attentions=token_attentions)
        return logits
