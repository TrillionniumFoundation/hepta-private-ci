"""Offline tensor surgery for a linear Cell readout on frozen Encoder features.

This is a bounded research primitive, not NeuronRuntime installation. A split
copies a readout AND adds a gate: extra tensors must fit the declared budget.
There is no promise that rank/capacity-reducing surgery preserves an arbitrary
parent. Real task learning requires approved features and future evaluation.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class TrainingBatch:
    features: torch.Tensor
    targets: torch.Tensor
    routes: torch.Tensor
    observed_at_ns: tuple[int, ...]
    source_digest: str

    def validate(self, dimension, classes, cutoff_ns):
        count = self.features.shape[0] if self.features.ndim == 2 else 0
        if not 1 <= count <= 4096 or self.features.shape != (count, dimension):
            raise ValueError("bounded frozen feature matrix required")
        if self.features.requires_grad or not torch.isfinite(self.features).all().item():
            raise ValueError("feature source must be frozen and finite")
        if self.features.device.type != "cpu" or self.features.dtype != torch.float32:
            raise ValueError("this reference profile is CPU float32 only")
        if self.targets.shape != (count,) or self.routes.shape != (count,):
            raise ValueError("one target and supervised route per training row required")
        for labels, ceiling in ((self.targets, classes), (self.routes, 2)):
            if labels.dtype != torch.long or labels.device.type != "cpu":
                raise ValueError("CPU integer labels required")
            if labels.min().item() < 0 or labels.max().item() >= ceiling:
                raise ValueError("label outside admitted classes")
        if type(cutoff_ns) is not int or cutoff_ns < 1 or len(self.observed_at_ns) != count:
            raise ValueError("training cutoff and row timestamps required")
        if any(type(t) is not int or not 0 < t <= cutoff_ns for t in self.observed_at_ns):
            raise ValueError("future labels cannot enter candidate training")
        if len(self.source_digest) != 64 or any(c not in "0123456789abcdef" for c in self.source_digest):
            raise ValueError("approved source identity required; not a permission grant")


class SparseSplitHead(nn.Module):
    """Two independent readouts, input-conditioned top-1 gate, no dense expert run."""

    def __init__(self, parent, *, parameter_cap):
        super().__init__()
        if not isinstance(parent, nn.Linear) or parent.out_features < 2:
            raise ValueError("a classification linear readout is required")
        if parent.weight.device.type != "cpu" or parent.weight.dtype != torch.float32:
            raise ValueError("reference split requires CPU float32 parent")
        if not all(torch.isfinite(p).all().item() for p in parent.parameters()):
            raise ValueError("nonfinite parent")
        required = 2 * sum(p.numel() for p in parent.parameters()) + 2 * (parent.in_features + 1)
        if type(parameter_cap) is not int or required > parameter_cap:
            raise ValueError("split plus gate exceeds physical parameter ceiling")
        self.dimension, self.classes = parent.in_features, parent.out_features
        self.children_heads = nn.ModuleList([copy.deepcopy(parent), copy.deepcopy(parent)])
        self.gate = nn.Linear(self.dimension, 2)
        nn.init.zeros_(self.gate.weight)
        nn.init.zeros_(self.gate.bias)
        self.parameter_cap = parameter_cap

    def forward(self, features):
        if (features.ndim != 2 or features.shape[1] != self.dimension
                or not 1 <= features.shape[0] <= 4096
                or features.device.type != "cpu" or features.dtype != torch.float32
                or not torch.isfinite(features).all().item()):
            raise ValueError("invalid bounded feature batch")
        routes = self.gate(features).argmax(dim=1)
        result = features.new_zeros((len(features), self.classes))
        for index, child in enumerate(self.children_heads):
            selected = torch.where(routes == index)[0]
            if selected.numel():
                # Only the selected subset executes this child; no evaluate-all
                # plus post-hoc mask disguised as sparse execution.
                result = result.index_copy(0, selected, child(features[selected]))
        return result


def tensor_inventory(module):
    """Count actual unique tensor storage; optimizer and activations are separate."""
    tensors = list(module.parameters()) + list(module.buffers())
    storages = {}
    for tensor in tensors:
        storage = tensor.untyped_storage()
        key = (str(tensor.device), storage.data_ptr())
        storages[key] = storage.nbytes()
    return {"parameters": sum(p.numel() for p in module.parameters()),
            "trainable_parameters": sum(p.numel() for p in module.parameters() if p.requires_grad),
            "unique_weight_bytes": sum(storages.values()),
            "optimizer_bytes": None, "activation_bytes": None}


def train_candidate(selected, batch, *, cutoff_ns, steps=32, learning_rate=.01):
    """Train a copy; gate supervision must come from the admitted training fold.

    Targets/route labels are not obtained by looking at future evaluation loss.
    A correct source digest is a linkage check, not independent data approval.
    """
    if not isinstance(selected, SparseSplitHead):
        raise ValueError("split candidate required")
    batch.validate(selected.dimension, selected.classes, cutoff_ns)
    if type(steps) is not int or not 1 <= steps <= 512:
        raise ValueError("bounded positive training steps required")
    if type(learning_rate) not in (int, float) or not 0 < learning_rate <= .1:
        raise ValueError("invalid learning rate")
    candidate = copy.deepcopy(selected)
    candidate.requires_grad_(True)
    candidate.train()
    optimizer = torch.optim.SGD(candidate.parameters(), lr=learning_rate)
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.cross_entropy(candidate.gate(batch.features), batch.routes)
        for index, child in enumerate(candidate.children_heads):
            subset = torch.where(batch.routes == index)[0]
            if subset.numel():
                loss = loss + nn.functional.cross_entropy(
                    child(batch.features[subset]), batch.targets[subset], reduction="sum") / len(batch.targets)
        loss.backward()
        nn.utils.clip_grad_norm_(candidate.parameters(), 1.0)
        optimizer.step()
        if not all(torch.isfinite(p).all().item() for p in candidate.parameters()):
            raise ValueError("nonfinite candidate weights")
    candidate.eval()
    inventory = tensor_inventory(candidate)
    if inventory["parameters"] > selected.parameter_cap:
        raise ValueError("candidate parameter ceiling exceeded")
    return candidate, {"steps": steps, "examples_seen": steps * len(batch.targets),
                       "source_digest": batch.source_digest, "inventory": inventory,
                       "measured_flops": None, "future_gain_established": False,
                       "production_authorized": False}


def merge_identical(candidate):
    """Only exact equal-child merge is function preserving for this hard gate.

    Divergent children need separately trained/evaluated distillation. Arbitrary
    weight averaging is intentionally not an implicit consolidation operation.
    """
    left, right = candidate.children_heads
    lstate, rstate = left.state_dict(), right.state_dict()
    if lstate.keys() != rstate.keys() or any(not torch.equal(lstate[k], rstate[k]) for k in lstate):
        raise ValueError("divergent experts require evaluated behavioral distillation")
    return copy.deepcopy(left)
