"""Post-training interventions: immutable learned weights, no retraining or routing leak."""
from __future__ import annotations

import copy

import numpy as np
import torch

from composition import CellCircuit, state_digest

LESIONS = ("intact", "no_semantic_message", "ungated_message", "permuted_channels", "no_direct_features")


@torch.no_grad()
def evaluate_lesions(model: CellCircuit, features: np.ndarray) -> dict:
    if model.mode != "joint" or features.ndim != 2 or not np.isfinite(features).all():
        raise ValueError("lesions require a trained joint circuit and finite features")
    if features.shape[1] != model.semantic.in_features or len(features) > 250_000:
        raise ValueError("lesion input shape/budget")
    before = state_digest(model)
    x = torch.as_tensor(features, dtype=torch.float32)
    semantic = torch.tanh(model.semantic(x))
    gates = torch.sigmoid(model.gate(x))
    probabilities = {}
    for lesion in LESIONS:
        direct, message = x, semantic * gates
        if lesion == "no_semantic_message":
            message = torch.zeros_like(message)
        elif lesion == "ungated_message":
            message = semantic
        elif lesion == "permuted_channels":
            message = torch.roll(semantic, shifts=1, dims=-1) * gates
        elif lesion == "no_direct_features":
            direct = torch.zeros_like(x)
        probabilities[lesion] = model.procedural(torch.cat([direct, message], dim=-1)).squeeze(-1).sigmoid().cpu().numpy()
    if state_digest(model) != before:
        raise RuntimeError("inference intervention changed learned parameters")
    return {
        "artifact_digest": before,
        "parameter_updates": 0,
        "intervention": "post-training-inference-only",
        "probabilities": probabilities,
    }


def clean_circuit(model: CellCircuit) -> CellCircuit:
    """Reconstruct from isolated immutable tensors, not hidden state or optimizer."""
    with torch.random.fork_rng(devices=[]):
        clean = CellCircuit(model.semantic.in_features, mode=model.mode)
    clean.load_state_dict(copy.deepcopy(model.state_dict()), strict=True)
    clean.eval().requires_grad_(False)
    return clean
