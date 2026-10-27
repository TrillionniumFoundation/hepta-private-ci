"""Small local adapters; the recovered million-parameter generator stays frozen."""

from copy import deepcopy
import hashlib
from pathlib import Path

import torch
from torch import nn

from ..v6.neural import parameter_hash
from .protocol import P


class LocalAdapter(nn.Module):
    def __init__(self, base, rank, generator):
        super().__init__()
        self.base = base.requires_grad_(False)
        self.down = nn.Parameter(torch.randn(rank, base.in_features, generator=generator)
                                 / base.in_features ** 0.5)
        self.up = nn.Parameter(torch.zeros(base.out_features, rank))

    def forward(self, inputs):
        return self.base(inputs) + (inputs @ self.down.T) @ self.up.T


def make_model(original, seed):
    model = deepcopy(original).cpu().eval().requires_grad_(False)
    generator = torch.Generator().manual_seed(seed * 917 + 271027)
    for name in P["adapter_modules"]:
        parent_name, _, leaf = name.rpartition(".")
        parent = model.get_submodule(parent_name) if parent_name else model
        base = parent.get_submodule(leaf)
        if not isinstance(base, nn.Linear):
            raise TypeError("Registered adapter location must be a Linear")
        setattr(parent, leaf, LocalAdapter(base, P["adapter_rank"], generator))
    return model


def local_parameters(model):
    return [parameter for parameter in model.parameters() if parameter.requires_grad]


def local_state(model):
    return {name: value.detach().clone() for name, value in model.named_parameters()
            if value.requires_grad}


def local_hash(model):
    digest = hashlib.sha256()
    for name, value in local_state(model).items():
        digest.update(name.encode())
        digest.update(value.contiguous().numpy().tobytes())
    return digest.hexdigest()


def displacement(model):
    groups = []
    for name in P["adapter_modules"]:
        module = model.get_submodule(name)
        delta = module.up @ module.down
        groups.append(float(delta.norm() / module.base.weight.norm().clamp_min(1e-12)))
    return groups


def save_adapter(path, model, optimizer, *, base_file_sha256, metadata):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema": "hepta.field-bridge.adapter.v1", "base_file_sha256": base_file_sha256,
              "adapter_modules": P["adapter_modules"], "rank": P["adapter_rank"],
              "parameters": local_state(model), "parameter_sha256": local_hash(model),
              "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
              "metadata": metadata}
    torch.save(record, path)
    reread = torch.load(path, map_location="cpu", weights_only=True)
    if any(not torch.equal(value, reread["parameters"][name])
           for name, value in record["parameters"].items()):
        raise RuntimeError("Adapter serialization changed parameters")
    return {"path": str(path), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "parameter_sha256": record["parameter_sha256"],
            "complete_optimizer_saved": optimizer is not None}


def load_adapter(path, original, seed, base_file_sha256):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if (record["schema"] != "hepta.field-bridge.adapter.v1"
            or record["base_file_sha256"] != base_file_sha256
            or record["adapter_modules"] != P["adapter_modules"]
            or record["rank"] != P["adapter_rank"]):
        raise ValueError("Incompatible adapter provenance")
    model = make_model(original, seed)
    destination = dict(model.named_parameters())
    if set(record["parameters"]) != set(local_state(model)):
        raise ValueError("Incomplete adapter tensor inventory")
    with torch.no_grad():
        for name, value in record["parameters"].items():
            destination[name].copy_(value)
    if local_hash(model) != record["parameter_sha256"]:
        raise ValueError("Adapter parameter identity mismatch")
    return model, record


def frozen_base_hash(model):
    digest = hashlib.sha256()
    for name, value in model.named_parameters():
        if not value.requires_grad:
            digest.update(name.encode())
            digest.update(value.detach().contiguous().numpy().tobytes())
    return digest.hexdigest()
