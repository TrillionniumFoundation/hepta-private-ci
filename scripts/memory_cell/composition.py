"""Learned two-cell evidence composition plus separately trained ablation controls.

Input: the same frozen query/document features for every arm. Semantic messages
are real differentiable activations, not an oracle category or target. The second
cell consumes the message through a learned gate. No authority crosses tensors.
"""
from __future__ import annotations

import copy
import hashlib
import time

import numpy as np
import torch
from torch import nn


class CellCircuit(nn.Module):
    def __init__(self, dimension: int, *, mode: str):
        super().__init__()
        if mode not in ("joint", "no_message", "shuffled_message", "frozen", "flat_matched"):
            raise ValueError("unknown ablation")
        self.mode = mode
        self.semantic = nn.Linear(dimension, 16)
        self.gate = nn.Linear(dimension, 16)
        self.procedural = nn.Linear(dimension + 16, 1)
        self.trainable_budget = sum(p.numel() for p in self.parameters())

    def forward(self, features):
        message = torch.tanh(self.semantic(features))
        gate = torch.sigmoid(self.gate(features))
        if self.mode == "no_message":
            message = message * 0
        elif self.mode == "shuffled_message":
            message = torch.roll(message, shifts=1, dims=0)
        elif self.mode == "flat_matched":
            # Same active tensors; an ungated feed-forward control, not idle padding.
            message = torch.tanh(self.semantic(features) + self.gate(features))
            gate = torch.ones_like(gate)
        return self.procedural(torch.cat([features, message * gate], dim=-1)).squeeze(-1)


def state_digest(model):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        h.update(name.encode())
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def fit(features: np.ndarray, labels: np.ndarray, partitions: list[str], *, steps: int = 48):
    if not 1 <= steps <= 512 or len(features) != len(labels) or len(features) != len(partitions):
        raise ValueError("composition dataset/budget")
    if not features.ndim == 2 or not np.isfinite(features).all() or not set(np.unique(labels)).issubset({0, 1}):
        raise ValueError("composition values")
    train = np.array([p == "train" for p in partitions])
    if train.sum() < 2 or len(set(labels[train].tolist())) != 2:
        raise ValueError("insufficient train-only class support")
    x = torch.tensor(features[train], dtype=torch.float32)
    y = torch.tensor(labels[train], dtype=torch.float32)
    outputs = {}
    for mode in ("joint", "no_message", "shuffled_message", "frozen", "flat_matched"):
        torch.manual_seed(1729)
        model = CellCircuit(features.shape[1], mode=mode)
        original = copy.deepcopy(model.state_dict())
        start = time.perf_counter()
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.003)
        for _ in range(0 if mode == "frozen" else steps):
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = nn.functional.binary_cross_entropy_with_logits(logits, y)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite composition loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            probabilities = model(torch.tensor(features, dtype=torch.float32)).sigmoid().numpy()
        outputs[mode] = (model, probabilities, {
            "parameter_budget": model.trainable_budget,
            "updated_parameters": sum(p.numel() for name, p in model.state_dict().items() if not torch.equal(original[name], p)),
            "steps": 0 if mode == "frozen" else steps,
            "train_examples": int(train.sum()), "train_seconds": time.perf_counter() - start,
            "artifact_digest": state_digest(model),
        })
    return outputs
