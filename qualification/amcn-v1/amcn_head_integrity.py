"""Exact physical SemanticMemoryCell Head materialization audit (not adoption).

Safetensors digest alone does not prove model geometry, finite tensor bytes,
training lineage or that logits were recomputed on original source inputs.
This verifier closes the first three gaps; original prediction execution must
still be independently re-run by the existing Hepta model owner.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import torch
from safetensors.torch import load_file
from safetensors import SafetensorError

from amcn_core import require, shadow_disposition
from experiments.shared_stem_cell.execution import Head, parameters


PROFILE = "hepta.amcn.sealed-semantic-head-material.v1"
MAX_MATERIAL_BYTES = 64 * 1024 * 1024


def validate_sealed_semantic_head(model_path: Path, receipt: dict):
    path = Path(model_path)
    require(path.is_file() and not path.is_symlink()
            and not any(parent.is_symlink() for parent in path.parents)
            and 0 < path.stat().st_size <= MAX_MATERIAL_BYTES,
            "missing/linked/oversized sealed Head")
    require(isinstance(receipt, dict) and receipt.get("schema") ==
            "hepta.amcn.real-head-candidate.v1" and
            receipt.get("production_accepted") is False,
            "original Head receipt is not a shadow candidate")
    blob = path.read_bytes()
    observed_sha = sha256(blob).hexdigest()
    require(receipt.get("head_tensor_sha256") == observed_sha,
            "Head bytes changed after model prediction")
    geometry = receipt.get("head_geometry")
    training = receipt.get("head_training")
    require(isinstance(geometry, dict) and
            set(geometry) == {"sha256", "parameters", "parameter_bytes"} and
            isinstance(training, dict) and
            isinstance(training.get("metrics"), dict) and
            isinstance(training["metrics"].get("trained"), dict),
            "missing physical Head training lineage")
    try:
        state = load_file(str(path), device="cpu")
    except (SafetensorError, ValueError, RuntimeError, OSError):
        require(False, "invalid Safetensors material")
    require("base.weight" in state and "base.bias" in state,
            "unexpected Head tensor layout")
    base = state["base.weight"]
    require(base.ndim == 2 and base.shape[0] == 2 and
            1 <= base.shape[1] <= 8192,
            "Head classes/hidden width")
    keys = set(state)
    if keys == {"base.weight", "base.bias"}:
        kind, rank = "linear", 1
    elif "down.weight" in keys and "up.weight" in keys:
        down = state["down.weight"]
        require(down.ndim == 2 and 1 <= down.shape[0] <= min(256, base.shape[1]),
                "Head adapter geometry")
        kind, rank = ("gated" if "gate.weight" in keys else "low_rank"), down.shape[0]
    else:
        require(False, "unknown Head parameter layout")
    model = Head(int(base.shape[1]), 2, kind=kind, rank=int(rank)).eval()
    # This also rejects unknown/extra/missing tensor names and invalid shapes.
    expected = set(model.state_dict())
    require(keys == expected, "unregistered Head tensors")
    require(all(isinstance(t, torch.Tensor) and
                t.dtype == torch.float32 and t.device.type == "cpu" and
                bool(torch.isfinite(t).all()) for t in state.values()),
            "nonfinite or non-FP32 Head weights")
    try:
        model.load_state_dict(state, strict=True)
    except (RuntimeError, ValueError):
        require(False, "Head tensor geometry differs from manifest")
    observed = parameters(model)
    require(observed == geometry, "Head parameter-count/digest mismatch")
    require(training["metrics"]["trained"] == observed,
            "trained Head model identity does not match saved material")
    return shadow_disposition(
        profile=PROFILE, model_bytes_sha256=observed_sha,
        actual_loaded_parameters=observed["parameters"],
        actual_head_kind=kind, tensor_state_sha256=observed["sha256"],
        safetensors_full_materialization_verified=True,
        all_tensors_finite=True,
        real_HF_encoder_parity_verified_here=False,
        original_predictions_reexecuted_here=False,
        independently_reviewed_semantic_recall=False,
    )
