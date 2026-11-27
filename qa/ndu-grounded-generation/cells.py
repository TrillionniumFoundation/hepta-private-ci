"""Four bounded, trainable residual Cells over a frozen decoder's logits.

These are a small research adapter, not the repository's production Cell runtime.
Only teacher-forced TRAIN references enter fitting. Inference accepts no reference.
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn


CELL_NAMES = ("semantic", "horizontal", "vertical", "completion")


class ResidualCell(nn.Module):
    def __init__(self, width, outputs, rank=16):
        super().__init__()
        self.down = nn.Linear(width, rank)
        self.up = nn.Linear(rank, outputs)
        nn.init.zeros_(self.up.weight)
        nn.init.zeros_(self.up.bias)

    def forward(self, hidden):
        return 3.0 * torch.tanh(self.up(torch.tanh(self.down(hidden))) / 3.0)


class FourCells(nn.Module):
    def __init__(self, width, vocabulary, locations, boundaries, rank=16):
        super().__init__()
        self.config = dict(width=width, vocabulary=list(vocabulary),
                           locations=list(locations), boundaries=list(boundaries), rank=rank)
        self.vocabulary = list(vocabulary)
        self.lookup = {token: i for i, token in enumerate(vocabulary)}
        self.locations = set(locations)
        self.boundaries = set(boundaries)
        semantic = [v for v in vocabulary if v not in self.locations | self.boundaries]
        groups = [semantic, list(locations), list(locations), list(boundaries)]
        if not semantic or any(v not in self.lookup for group in groups for v in group):
            raise ValueError("complete train vocabulary and nonempty semantic Cell required")
        self.groups = [[self.lookup[v] for v in group] for group in groups]
        self.cells = nn.ModuleList(ResidualCell(width, len(group), rank) for group in groups)

    def corrections(self, hidden):
        values = hidden.new_zeros((*hidden.shape[:-1], 4, len(self.vocabulary)))
        for i, (cell, group) in enumerate(zip(self.cells, self.groups)):
            values[..., i, group] = cell(hidden)
        return values

    def delta(self, hidden, weights, vocabulary_size):
        corrections = self.corrections(hidden)
        combined = torch.as_tensor(weights, dtype=hidden.dtype) @ corrections
        delta = hidden.new_zeros(vocabulary_size)
        delta[self.vocabulary] = combined
        return delta, corrections

    def fit(self, bank, epochs=15, learning_rate=0.003, seed=23):
        """Retain the frozen softmax's outside mass, subject to float precision."""
        torch.manual_seed(seed)
        hidden = torch.as_tensor(bank["hidden"], dtype=torch.float32)
        logits = torch.as_tensor(bank["logits"], dtype=torch.float32)
        log_z = torch.as_tensor(bank["full_logsumexp"], dtype=torch.float32)
        target_ids = np.asarray(bank["target_ids"])
        targets = torch.tensor([self.lookup[int(token)] for token in target_ids])
        roles = torch.as_tensor(bank["roles"], dtype=torch.long)
        if hidden.ndim != 2 or logits.shape != (len(hidden), len(self.vocabulary)):
            raise ValueError("teacher feature bank shape mismatch")
        # log(1 - exp(a)) uses double precision to preserve the unmodified mass.
        fraction = (torch.logsumexp(logits.double(), -1) - log_z.double()).clamp(max=-1e-12)
        outside = (log_z.double() + torch.log(-torch.expm1(fraction))).float()
        optimizer = torch.optim.AdamW(self.parameters(), lr=learning_rate, weight_decay=0.01)
        started, history = time.perf_counter(), []
        self.train()
        for epoch in range(epochs):
            losses = []
            for indices in torch.randperm(len(hidden)).split(64):
                corrections = self.corrections(hidden[indices])
                terms = []
                for cell in range(4):
                    mask = torch.ones(len(indices), dtype=torch.bool) if cell == 3 else roles[indices].eq(cell)
                    if not bool(mask.any()):
                        continue
                    adjusted = logits[indices][mask] + corrections[mask, cell]
                    denominator = torch.logaddexp(torch.logsumexp(adjusted, -1), outside[indices][mask])
                    chosen = adjusted.gather(1, targets[indices][mask, None]).squeeze(1)
                    terms.append((denominator - chosen).mean() + 0.002 * corrections[mask, cell].square().mean())
                loss = torch.stack(terms).mean()
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.parameters(), 2.0)
                optimizer.step()
                losses.append(float(loss.detach()))
            history.append(float(np.mean(losses)))
        self.eval()
        return dict(epochs=epochs, samples=len(hidden), losses=history,
                    seconds=time.perf_counter() - started,
                    trainable_parameters=sum(p.numel() for p in self.parameters()),
                    training_source="train_only_teacher_forcing")

    def save(self, path):
        torch.save({"config": self.config, "state": self.state_dict()}, path)
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        saved = torch.load(path, map_location="cpu", weights_only=True)
        model = cls(**saved["config"])
        model.load_state_dict(saved["state"])
        return model.eval()


def target_text(reference):
    """Training only: serialize COCO boxes to Florence's location vocabulary."""
    pieces = [reference["label"]]
    for box in sorted(reference["boxes"], key=lambda b: (b[0], b[1])):
        pieces.extend(f"<loc_{min(999, max(0, int(float(x) * 1000)))}>" for x in box)
    return "".join(pieces)


def token_roles(ids, location_ids, boundaries):
    roles, coordinate = [], 0
    locations, boundaries = set(location_ids), set(boundaries)
    for token in ids:
        token = int(token)
        if token in locations:
            roles.append(1 if coordinate % 2 == 0 else 2)
            coordinate += 1
        else:
            roles.append(3 if token in boundaries else 0)
    return roles


def state_features(state, corrections, vocabulary, location_ids, eos_token):
    """Small observed state: uncertainty, prefix geometry and Cell disagreement."""
    logits = state["logits"].float()
    probabilities = logits.softmax(-1)
    top = probabilities.topk(2).values
    entropy = torch.special.entr(probabilities).sum() / np.log(len(logits))
    locations = set(location_ids)
    coordinates = [token for token in state["token_ids"] if token in locations]
    phase = len(coordinates) % 4
    sparse_p = probabilities[vocabulary]
    mean = corrections @ sparse_p
    covariance = (corrections * sparse_p) @ corrections.T - mean[:, None] * mean[None, :]
    norms = corrections.square().mean(-1).sqrt()
    features = [state["step"] / 48, min(1.0, state["remaining_seconds"] / 30),
                float(entropy), float(top[0]), float(top[0] - top[1]),
                len(coordinates) / 12, float(bool(state["token_ids"] and state["token_ids"][-1] in locations)),
                float(probabilities[eos_token]), *[float(phase == i) for i in range(4)],
                *norms.tolist(), *mean.tolist(), *covariance.diag().tolist()]
    return np.asarray(features, dtype=np.float32), covariance


def apply_constraints(logits, prefix, location_ids, eos_token):
    """Observable syntax/geometry constraints, with no image-reference access."""
    constrained = logits.clone()
    lookup = {token: i for i, token in enumerate(location_ids)}
    coordinates = [lookup[token] for token in prefix if token in lookup]
    phase = len(coordinates) % 4
    if phase:
        # Inside a box only location tokens are grammatical; retain no lexical
        # escape from a half-written box. These are syntax constraints only.
        allowed = constrained[location_ids].clone()
        constrained.fill_(-float("inf"))
        constrained[location_ids] = allowed
    if phase in (0, 1):
        # x1/y1 must leave room for a strictly larger x2/y2.
        constrained[location_ids[-1]] = -float("inf")
    if phase in (2, 3):
        lower = coordinates[-2]
        constrained[location_ids[:lower + 1]] = -float("inf")
    if not bool(torch.isfinite(constrained).any()):
        # A malformed prefix is an execution failure, not a guessed rectangle.
        raise ValueError("no feasible token under geometry constraints")
    return constrained


def stable_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
