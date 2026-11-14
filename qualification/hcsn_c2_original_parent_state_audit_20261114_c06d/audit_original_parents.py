#!/usr/bin/env python3
"""Read-only semantic inventory of six recovered original C2 parent checkpoints.

The program verifies exact bytes before importing Torch, uses weights_only=True,
constructs no model or optimizer, and performs no forward, backward, or update.
"""

import hashlib
import json
import resource
from pathlib import Path


PARENTS = [
    {
        "fit": "hcsn-s101-lr0.001",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s101-lr0.001/last.pt",
        "sha256": "e0c8c946aa8010bfcf4df5b9e155235d2fb6b12a9832e4eaa5db3d9afb154d78",
        "size": 450552,
        "epoch": 46,
        "main_updates": 552,
    },
    {
        "fit": "hcsn-s101-lr0.003",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s101-lr0.003/last.pt",
        "sha256": "bea446e64571e7cd424411036eff207bb6839af4495a7b60cf0f9df81181ba05",
        "size": 450616,
        "epoch": 47,
        "main_updates": 564,
    },
    {
        "fit": "hcsn-s211-lr0.001",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s211-lr0.001/last.pt",
        "sha256": "cdbca6e633c6aba5f72f08f259ab08b1c5c2c5745d1dbd2f323a78df876e1e79",
        "size": 450552,
        "epoch": 46,
        "main_updates": 552,
    },
    {
        "fit": "hcsn-s211-lr0.003",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s211-lr0.003/last.pt",
        "sha256": "b7d162101f18628fcfcabb21e9609499d62c8a26ad6d53b9c375ed2e0439d2f4",
        "size": 450488,
        "epoch": 47,
        "main_updates": 564,
    },
    {
        "fit": "hcsn-s307-lr0.001",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s307-lr0.001/last.pt",
        "sha256": "17d6ad363d82ba31b006d0a4f55ca9c63453fa2c9c34f7370f022e2ff66a4f5c",
        "size": 450552,
        "epoch": 46,
        "main_updates": 552,
    },
    {
        "fit": "hcsn-s307-lr0.003",
        "path": "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2/hcsn-s307-lr0.003/last.pt",
        "sha256": "736ee7d7afe911a3cf5bb7f7ad97babff4dfb74e28a46ec9c148579160a5075c",
        "size": 450552,
        "epoch": 46,
        "main_updates": 552,
    },
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            value.update(block)
            size += len(block)
    return {"sha256": value.hexdigest(), "size": size}


def walk_tensors(value, torch, prefix="root"):
    rows = []
    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu()
        nonfinite = 0
        if tensor.is_floating_point() or tensor.is_complex():
            nonfinite = int((~torch.isfinite(tensor)).sum().item())
        rows.append(
            {
                "path": prefix,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype),
                "device": str(value.device),
                "numel": value.numel(),
                "nonfinite": nonfinite,
            }
        )
    elif isinstance(value, dict):
        for key in sorted(value, key=lambda item: str(item)):
            rows.extend(walk_tensors(value[key], torch, prefix + "." + str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            rows.extend(walk_tensors(item, torch, prefix + "[" + str(index) + "]"))
    return rows


def main():
    for parent in PARENTS:
        require(digest(parent["path"]) == {
            "sha256": parent["sha256"],
            "size": parent["size"],
        }, "parent bytes differ before Torch import: " + parent["fit"])

    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    rows = []
    required = {
        "model",
        "model_configuration",
        "optimizer",
        "torch_rng",
        "order_rng",
        "epochs_completed",
        "main_updates",
        "data_manifest_sha256",
    }

    for parent in PARENTS:
        state = torch.load(parent["path"], map_location="cpu", weights_only=True)
        require(type(state) is dict, "checkpoint is not an exact dict: " + parent["fit"])
        require(required.issubset(state), "required state missing: " + parent["fit"])
        require(
            type(state["epochs_completed"]) is int
            and state["epochs_completed"] == parent["epoch"],
            "epoch differs: " + parent["fit"],
        )
        require(
            type(state["main_updates"]) is int
            and state["main_updates"] == parent["main_updates"],
            "main update count differs: " + parent["fit"],
        )
        require(
            isinstance(state["model"], dict) and bool(state["model"]),
            "model state is empty: " + parent["fit"],
        )
        require(
            isinstance(state["model_configuration"], dict)
            and bool(state["model_configuration"]),
            "model configuration is empty: " + parent["fit"],
        )
        require(
            isinstance(state["optimizer"], dict) and bool(state["optimizer"]),
            "optimizer state is empty: " + parent["fit"],
        )
        require(
            isinstance(state["data_manifest_sha256"], str)
            and len(state["data_manifest_sha256"]) == 64,
            "data manifest identity is invalid: " + parent["fit"],
        )

        tensors = walk_tensors(state, torch)
        model_tensors = walk_tensors(state["model"], torch, "model")
        optimizer_tensors = walk_tensors(
            state["optimizer"], torch, "optimizer"
        )
        require(all(item["device"] == "cpu" for item in tensors), "non-CPU tensor")
        require(
            sum(item["nonfinite"] for item in tensors) == 0,
            "nonfinite tensor value: " + parent["fit"],
        )

        optimizer = state["optimizer"]
        optimizer_state = optimizer.get("state")
        parameter_groups = optimizer.get("param_groups")
        require(
            isinstance(optimizer_state, dict) and bool(optimizer_state),
            "optimizer slots are empty: " + parent["fit"],
        )
        require(
            isinstance(parameter_groups, list) and bool(parameter_groups),
            "optimizer parameter groups are empty: " + parent["fit"],
        )

        rows.append(
            {
                "fit": parent["fit"],
                "path": parent["path"],
                "sha256": parent["sha256"],
                "size": parent["size"],
                "top_level_keys": sorted(state),
                "epoch": state["epochs_completed"],
                "main_updates": state["main_updates"],
                "model_state_entries": len(state["model"]),
                "model_configuration_keys": sorted(state["model_configuration"]),
                "optimizer_state_entries": len(optimizer_state),
                "optimizer_parameter_groups": len(parameter_groups),
                "torch_rng_type": type(state["torch_rng"]).__name__,
                "order_rng_type": type(state["order_rng"]).__name__,
                "cursor_key_present": "cursor" in state,
                "data_manifest_sha256": state["data_manifest_sha256"],
                "tensor_count": len(tensors),
                "tensor_numel": sum(item["numel"] for item in tensors),
                "model_tensor_count": len(model_tensors),
                "model_tensor_numel": sum(
                    item["numel"] for item in model_tensors
                ),
                "optimizer_tensor_count": len(optimizer_tensors),
                "optimizer_tensor_numel": sum(
                    item["numel"] for item in optimizer_tensors
                ),
                "nonfinite_tensor_values": 0,
                "all_tensors_cpu": True,
            }
        )

        require(digest(parent["path"]) == {
            "sha256": parent["sha256"],
            "size": parent["size"],
        }, "parent bytes changed after load: " + parent["fit"])

    result = {
        "schema": "hcsn-c2-original-parent-state-audit-v1",
        "identity": "hcsn-c2-original-parent-state-audit-20261114-c06d-v1",
        "status": "EVIDENCE_ONLY_HOLD",
        "torch": torch.__version__,
        "torch_build": torch.version.git_version,
        "weights_only": True,
        "parents_verified": len(rows),
        "rows": rows,
        "torch_imports": 1,
        "torch_loads": len(rows),
        "model_constructions": 0,
        "forward_calls": 0,
        "backward_calls": 0,
        "optimizer_constructions": 0,
        "optimizer_calls": 0,
        "original_replay_restarted": False,
        "full_training_replay_completed_fits": "0/6",
        "all_closed": False,
    }
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
