"""Actually executed shared-feature Cell bank; no split/NDU claim.

Dense and sparse variants have the same gate/head tensors. For 16/32 cells,
widths are chosen so actual total trainable counts match at equal feature width
and width_units: N*(d+c+1)*(width+1)=32*(d+c+1)*width_units.
The explicit 64M control doubles that capacity; it is not only a new label.
"""
import hashlib

import torch
from torch import nn

from head_surgery import tensor_inventory


class CellBank(nn.Module):
    """Input-dependent gated heads; only routed sample subsets execute."""

    def __init__(self, dimension, classes, profile, width_units):
        super().__init__()
        if (type(dimension) is not int or not 1 <= dimension <= 8192
                or type(classes) is not int or not 2 <= classes <= 16
                or type(width_units) is not int or not 1 <= width_units <= 1024):
            raise ValueError("invalid bounded Cell geometry")
        count = profile["logical_cells"]
        if (count not in (16, 32) or profile["initial_logical_cells"] != count
                or profile["split"] is not False or profile["ndu"] is not False
                or profile["resident_stem_copies"] != 1):
            raise ValueError("profile requires an unimplemented executor")
        capacity = profile["total_head_budget_params"] // 32_000_000
        if capacity not in (1, 2):
            raise ValueError("unregistered capacity multiplier")
        width = (32 // count) * width_units * capacity - 1
        if width < 1:
            raise ValueError("width_units must leave a nonempty hidden layer")
        per_head = (dimension + classes + 1) * width + classes
        if per_head > profile["cell_head_budget_params"]:
            raise ValueError("Head exceeds the admitted per-Cell allocation")
        self.dimension, self.classes = dimension, classes
        self.top_k = profile["active_cells_per_round_cap"]
        if type(self.top_k) is not int or not 1 <= self.top_k <= count:
            raise ValueError("invalid sparse activation limit")
        self.gate = nn.Linear(dimension, count)
        self.heads = nn.ModuleList([nn.Sequential(nn.Linear(dimension, width), nn.GELU(),
                                                nn.Linear(width, classes)) for _ in range(count)])
        self.executed_rows = [0] * count
        self.calls = 0
        self.gate_parameter_count = sum(p.numel() for p in self.gate.parameters())
        self.head_parameter_count = sum(p.numel() for p in self.heads.parameters())
        total = self.head_parameter_count + self.gate_parameter_count
        if total != 32 * (dimension + classes + 1) * width_units * capacity:
            raise ValueError("unexpected bank tensor inventory")
        # Also cap all trainable parameters, rather than hide the gate outside
        # the nominal Head-only envelope. Actual counts are retained separately.
        if total > profile["total_head_budget_params"]:
            raise ValueError("Head plus gate exceeds the total allocation")

    def forward(self, features):
        if (features.ndim != 2 or features.shape[1] != self.dimension
                or not 1 <= len(features) <= 4096 or features.dtype != torch.float32
                or features.device.type != "cpu" or not torch.isfinite(features).all().item()):
            raise ValueError("bounded CPU FP32 features required")
        scores = self.gate(features)
        # Stable sort gives explicit cell-index tie ordering.
        routes = torch.argsort(scores, dim=1, descending=True, stable=True)[:, :self.top_k]
        weights = scores.gather(1, routes).softmax(1)
        output = features.new_zeros((len(features), self.classes))
        for index, head in enumerate(self.heads):
            selected, slot = torch.where(routes == index)
            if selected.numel():
                output = output.index_add(0, selected, head(features[selected]) * weights[selected, slot, None])
                self.executed_rows[index] += len(selected)
        self.calls += 1
        return output

    def training_loss(self, features, targets):
        return nn.functional.cross_entropy(self(features), targets)

    def inventory(self):
        return {**tensor_inventory(self), "head_params": self.head_parameter_count,
                "gate_params": self.gate_parameter_count, "cells": len(self.heads),
                "active_cells_cap": self.top_k, "calls": self.calls,
                "executed_rows": list(self.executed_rows)}


def state_digest(module):
    digest = hashlib.sha256(b"hepta.cell-bank.actual-state.v1\0")
    for name, tensor in sorted(module.state_dict().items()):
        tensor = tensor.detach().cpu().contiguous()
        descriptor = f"{name}:{tensor.dtype}:{tuple(tensor.shape)}".encode()
        raw = memoryview(tensor.reshape(-1).view(torch.uint8).numpy())
        for chunk in (descriptor, raw):
            digest.update(len(chunk).to_bytes(8, "big"))
            digest.update(chunk)
    return digest.hexdigest()


def train_bank(bank, features, targets, config, seed):
    if (features.requires_grad or features.ndim != 2 or not 1 <= len(features) <= 4096
            or targets.shape != (len(features),) or targets.dtype != torch.long
            or targets.device.type != "cpu" or targets.min().item() < 0
            or targets.max().item() >= bank.classes):
        raise ValueError("frozen training features and valid CPU labels required")
    rng = torch.Generator(device="cpu").manual_seed(seed)
    optimizer = torch.optim.AdamW(bank.parameters(), lr=.001, weight_decay=.01)
    bank.train()
    losses = []
    for _ in range(config["train_steps"]):
        ids = torch.randint(len(targets), (min(config["batch_size"], len(targets)),), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        loss = bank.training_loss(features[ids], targets[ids])
        if not torch.isfinite(loss).item():
            raise ValueError("nonfinite training loss")
        loss.backward()
        nn.utils.clip_grad_norm_(bank.parameters(), 1.0)
        optimizer.step()
        losses.append(float(loss.detach()))
    if not all(torch.isfinite(p).all().item() for p in bank.parameters()):
        raise ValueError("nonfinite trained candidate")
    # Adam optimizer is not resident at inference; keep its measured tensor size.
    optimizer_bytes = sum(v.numel() * v.element_size() for state in optimizer.state.values()
                          for v in state.values() if isinstance(v, torch.Tensor))
    bank.eval()
    return {"steps": len(losses), "examples_seen": len(losses) * min(config["batch_size"], len(targets)),
            "losses": losses, "optimizer_tensor_bytes": optimizer_bytes}
