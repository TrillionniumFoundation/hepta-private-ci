"""Research-only answer-aware Cell Head on ONE frozen shared token encoder.

The source/training owner provides source-bound TRAIN labels.  Held prediction
rows contain no labels.  This module does not decide model promotion, NDU
utility, source truth, or any external effects.  No current Hepta native API.
"""

from dataclasses import dataclass
import math
import time
from collections import defaultdict

import torch
from torch import nn
from torch.nn import functional as F

from e27_material_contract import (
    AUTHORITY, SCHEMA, MAX_TOKENS, canonical_sha, validate_material,
)

SEED = 27016
RANK = 16
HIDDEN = 32
TRAIN_STEPS = 64
LR = 0.002


class TokenInteractionHead(nn.Module):
    """Cell-specific 4-way low-rank evidence/question/answer interaction.

    `answer_visible=False` holds model size, token features and full forward
    count constant while setting answer information to zero INSIDE the head.
    Neither mode copies the frozen encoder parameters into this head.
    """

    def __init__(self, d_model: int):
        super().__init__()
        if type(d_model) is not int or not 4 <= d_model <= 2048:
            raise ValueError('invalid fixed shared encoder dimension')
        self.evidence = nn.Linear(d_model, RANK, bias=False)
        self.question = nn.Linear(d_model, RANK, bias=False)
        self.answer = nn.Linear(d_model, RANK, bias=False)
        self.joint = nn.Linear(4 * RANK, HIDDEN)
        self.out = nn.Linear(HIDDEN, 1)

    def forward(self, evidence, question, answer, *, answer_visible=True):
        if (evidence.ndim != 2 or question.ndim != 1 or answer.ndim != 1 or
            evidence.shape[0] < 1 or evidence.shape[1] != question.numel() or
            question.shape != answer.shape):
            raise ValueError('bad shared token / candidate dimensions')
        e = self.evidence(evidence)
        q = self.question(question)
        a = self.answer(answer) if answer_visible else torch.zeros_like(q)
        weights = torch.softmax(e @ (q + a) / math.sqrt(RANK), dim=0)
        context = weights @ e
        joint = torch.cat((q, a, context, a * context))
        return self.out(F.gelu(self.joint(joint))).squeeze()


@dataclass(frozen=True)
class CachedFeature:
    evidence: torch.Tensor
    question: torch.Tensor
    answer: torch.Tensor
    source_group: str
    question_id: str
    candidate_id: str
    label: int | None


def make_feature_bank(material, *, embedder):
    """Physically encode each passage/question/answer once in one shared model.

    This reuses IMMUTABLE source token computation within a compatible scope;
    weights, tokenizer, normalization and device are frozen outside this API.
    """
    mode = material['role']
    validate_material(material, mode=mode)
    features = []
    calls = 0
    for group in material['groups']:
        e = embedder(group['evidence'], token_sequence=True)
        calls += 1
        if type(e) is not torch.Tensor or e.ndim != 2 or e.shape[0] < 1:
            raise ValueError('frozen encoder returned wrong evidence shape')
        for q in group['questions']:
            question = embedder(q['text'], token_sequence=False)
            calls += 1
            if type(question) is not torch.Tensor or question.ndim != 1:
                raise ValueError('bad question projection')
            for c in q['candidates']:
                answer = embedder(c['text'], token_sequence=False)
                calls += 1
                if type(answer) is not torch.Tensor or answer.shape != question.shape or not (
                    torch.isfinite(e).all() and torch.isfinite(question).all() and torch.isfinite(answer).all()
                ):
                    raise ValueError('nonfinite or mismatched frozen encoder features')
                if any(t.requires_grad for t in (e, question, answer)):
                    raise ValueError('frozen shared encoder must emit detached features')
                features.append(CachedFeature(e, question, answer, group['group_id'],
                                              q['question_id'], c['candidate_id'], c.get('label')))
    # No optimizer touches immutable encoder or feature bank.
    return tuple(features), calls


def train_head(features, *, answer_visible):
    """Train-only supervised candidate BCE and within-question contrastive loss.

    Same initial weights, support, optimizer steps and mathematical head topology
    for both arms. No held labels, rewards, model selection or future leakage.
    """
    if (type(answer_visible) is not bool or not features or
        any(f.label not in (0, 1) for f in features)):
        raise ValueError('train source must carry real binary labels')
    grouped = defaultdict(list)
    for f in features:
        grouped[(f.source_group, f.question_id)].append(f)
    if not any({0, 1} <= {f.label for f in rows} for rows in grouped.values()):
        raise ValueError('missing within-question contrastive support')
    torch.manual_seed(SEED)
    model = TokenInteractionHead(features[0].question.numel())
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.0001)
    order = tuple(sorted(grouped))
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    for step in range(TRAIN_STEPS):
        # Exact one whole-question minibatch, deterministic and arm-balanced.
        batch = grouped[order[step % len(order)]]
        logits = torch.stack([model(f.evidence, f.question, f.answer,
                                    answer_visible=answer_visible) for f in batch])
        truth = torch.tensor([f.label for f in batch], dtype=logits.dtype)
        positives = logits[truth == 1]
        negatives = logits[truth == 0]
        loss = F.binary_cross_entropy_with_logits(logits, truth)
        if positives.numel() and negatives.numel():
            loss = loss + 0.25 * F.softplus(-(positives[:, None] - negatives[None, :])).mean()
        if not torch.isfinite(loss):
            raise ValueError('unstable candidate learning objective')
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
    cpu_ns, wall_ns = time.process_time_ns() - start_cpu, time.perf_counter_ns() - start_wall
    model.eval()
    return model, {'fit_cpu_ns': cpu_ns, 'fit_wall_ns': wall_ns,
                   'optimizer_steps': TRAIN_STEPS, 'parameter_count': sum(t.numel() for t in model.parameters()),
                   'question_batches': len(order), 'training_examples': len(features),
                   'answer_visible': answer_visible}


def blind_predict(features, aware, muted):
    """Emit candidate probabilities only; original held truth is not accessible."""
    if not features or any(f.label is not None for f in features):
        raise ValueError('held truth is accessible at blind inference')
    rows = []
    with torch.inference_mode():
        for f in features:
            logits = {
                'aware': float(aware(f.evidence, f.question, f.answer, answer_visible=True)),
                'answer_muted': float(muted(f.evidence, f.question, f.answer, answer_visible=False)),
            }
            if not all(math.isfinite(x) and abs(x) < 100 for x in logits.values()):
                raise ValueError('invalid source-blind probability')
            rows.append(dict(source_group=f.source_group, question_id=f.question_id,
                             candidate_id=f.candidate_id, logits=logits))
    return rows
