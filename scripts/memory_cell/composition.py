"""Learned, scope-local messages and equal-allocation ablation controls."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

MODES = (
    "joint",
    "cell_only",
    "routing_only",
    "no_message",
    "shuffled_message",
    "frozen",
    "flat_matched",
)


class CellCircuit(nn.Module):
    def __init__(self, dimension: int, *, mode: str):
        super().__init__()
        if mode not in MODES or not 1 <= dimension <= 512:
            raise ValueError("unknown ablation or input dimension")
        self.mode = mode
        self.semantic = nn.Linear(dimension, 16)
        self.gate = nn.Linear(dimension, 16)
        self.procedural = nn.Linear(dimension + 16, 1)
        self.trainable_budget = sum(p.numel() for p in self.parameters())
        if mode == "cell_only":
            self.gate.requires_grad_(False)
        elif mode == "routing_only":
            self.semantic.requires_grad_(False)
            self.procedural.requires_grad_(False)
        elif mode == "frozen":
            self.requires_grad_(False)
        elif mode == "no_message":
            self.semantic.requires_grad_(False)
            self.gate.requires_grad_(False)

    def forward(self, features):
        if self.mode == "no_message":
            message = features.new_zeros(
                (*features.shape[:-1], self.semantic.out_features)
            )
        elif self.mode == "flat_matched":
            message = torch.tanh(self.semantic(features) + self.gate(features))
        else:
            message = torch.tanh(self.semantic(features))
            gate = torch.sigmoid(self.gate(features))
            if self.mode == "shuffled_message":
                # A retrained architecture control; the post-training lesion is
                # evaluated separately and never relearns a channel permutation.
                message = torch.roll(message, shifts=1, dims=-1)
            message = message * gate
        return self.procedural(torch.cat([features, message], dim=-1)).squeeze(-1)


def state_digest(model):
    h = hashlib.sha256(b"hepta.memory-circuit.tensor-state.v2\0")
    for name, tensor in sorted(model.state_dict().items()):
        header = json.dumps(
            [name, str(tensor.dtype), list(tensor.shape)], separators=(",", ":")
        ).encode()
        h.update(len(header).to_bytes(8, "big"))
        h.update(header)
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def fit(
    features: np.ndarray,
    labels: np.ndarray,
    partitions: list[str],
    *,
    steps: int = 48,
    family_ids: list[str] | None = None,
):
    if (
        not 1 <= steps <= 512
        or len(features) != len(labels)
        or len(features) != len(partitions)
    ):
        raise ValueError("composition dataset/budget")
    if (
        features.ndim != 2
        or not np.isfinite(features).all()
        or not set(np.unique(labels)).issubset({0, 1})
    ):
        raise ValueError("composition values")
    if not set(partitions).issubset({"train", "select", "test"}):
        raise ValueError("unknown data partition")
    train = np.array([p == "train" for p in partitions])
    if train.sum() < 2 or len(set(labels[train].tolist())) != 2:
        raise ValueError("insufficient train-only class support")
    weights = np.ones(int(train.sum()), dtype=np.float32)
    family_count = None
    if family_ids is not None:
        if len(family_ids) != len(partitions):
            raise ValueError("source-family alignment")
        owner, counts = {}, {}
        for family, phase in zip(family_ids, partitions, strict=True):
            if not isinstance(family, str) or not 1 <= len(family) <= 1024:
                raise ValueError("source-family identity")
            if owner.setdefault(family, phase) != phase:
                raise ValueError("source family crosses training/selection/test")
            if phase == "train":
                counts[family] = counts.get(family, 0) + 1
        family_count = len(counts)
        weights = np.asarray(
            [
                1 / counts[f]
                for f, phase in zip(family_ids, partitions, strict=True)
                if phase == "train"
            ],
            dtype=np.float32,
        )
        weights /= weights.mean()
    sample_weights = torch.tensor(weights)
    x = torch.tensor(features[train], dtype=torch.float32)
    y = torch.tensor(labels[train], dtype=torch.float32)
    outputs = {}
    for mode in MODES:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(1729)
            model = CellCircuit(features.shape[1], mode=mode)
        original = copy.deepcopy(model.state_dict())
        start = time.perf_counter()
        optimized = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(optimized, lr=0.003) if optimized else None
        for _ in range(0 if mode == "frozen" else steps):
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.binary_cross_entropy_with_logits(
                model(x), y, reduction="none"
            )
            loss = (loss * sample_weights).mean()
            if not torch.isfinite(loss):
                raise ValueError("nonfinite composition loss")
            loss.backward()
            nn.utils.clip_grad_norm_(optimized, 1.0, error_if_nonfinite=True)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            probabilities = (
                model(torch.tensor(features, dtype=torch.float32)).sigmoid().numpy()
            )
        outputs[mode] = (
            model,
            probabilities,
            {
                "parameter_budget": model.trainable_budget,
                "optimizer_parameter_count": sum(p.numel() for p in optimized),
                "updated_parameters": sum(
                    p.numel()
                    for name, p in model.state_dict().items()
                    if not torch.equal(original[name], p)
                ),
                "steps": 0 if mode == "frozen" else steps,
                "train_examples": int(train.sum()),
                "training_source_families": family_count,
                "loss_weighting": "equal-source-family"
                if family_ids is not None
                else "fixture-row-mean",
                "parameter_bytes": sum(
                    p.numel() * p.element_size() for p in model.parameters()
                ),
                "optimizer_tensor_bytes": sum(
                    v.numel() * v.element_size()
                    for state in (optimizer.state.values() if optimizer else [])
                    for v in state.values()
                    if isinstance(v, torch.Tensor)
                ),
                "budget_kind": "equal-allocated-parameters-not-equal-effective-computation",
                "message_semantics": "row-local-gated-semantic-representation",
                "train_seconds": time.perf_counter() - start,
                "artifact_digest": state_digest(model),
                "message_permutation": "per-request-channels"
                if mode == "shuffled_message"
                else None,
            },
        )
    return outputs


def export_native(
    model,
    directory: Path,
    encoder_digest: str,
    dataset_digest: str,
    scope_digest: str,
    inputs: np.ndarray,
):
    """Export the actual trained joint tensors plus Q24 parity inputs for Rust."""
    if model.mode != "joint" or any(
        len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
        for value in (encoder_digest, dataset_digest, scope_digest)
    ):
        raise ValueError("native export profile/binding")
    directory.mkdir(parents=True, exist_ok=False)
    state = model.state_dict()
    circuit = {
        "schema": "hepta.memory-circuit.v1",
        "encoder_digest": encoder_digest,
        "dataset_digest": dataset_digest,
        "scope_digest": scope_digest,
        "output_profile": "relevance-state-five-v1",
        "dimension": model.semantic.in_features,
        "hidden": model.semantic.out_features,
    }
    for name in (
        "semantic.weight",
        "semantic.bias",
        "gate.weight",
        "gate.bias",
        "procedural.weight",
    ):
        circuit[name.replace(".", "_")] = state[name].flatten().tolist()
    circuit["procedural_bias"] = float(state["procedural.bias"].item())
    payload = json.dumps(
        circuit, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(payload) > 512 * 1024:
        raise ValueError("native artifact byte bound")
    (directory / "circuit.json").write_bytes(payload)
    quantized = np.rint(inputs[:32] * (1 << 24)).astype(np.int64)
    if (
        quantized.ndim != 2
        or quantized.shape[1] != circuit["dimension"]
        or np.abs(quantized).max() > 8 << 24
    ):
        raise ValueError("native input bound")
    with torch.no_grad():
        probabilities = (
            model(torch.tensor(quantized / (1 << 24), dtype=torch.float32))
            .sigmoid()
            .numpy()
        )
    vectors = [
        {
            "input_q24": values.tolist(),
            "expected_probability_q24": int(round(float(p) * (1 << 24))),
        }
        for values, p in zip(quantized, probabilities, strict=True)
    ]
    (directory / "parity.json").write_text(
        json.dumps(
            {
                "weights_sha256": hashlib.sha256(payload).hexdigest(),
                "maximum_absolute_q24_error": 64,
                "vectors": vectors,
                "trained_tensor_digest": state_digest(model),
            },
            indent=2,
        )
    )
