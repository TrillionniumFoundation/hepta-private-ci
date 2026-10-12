"""Explicit derived snapshot for one pinned public BGE checkpoint, research only.

The generic inference loader stays strict. Preserve original weights separately;
remove exactly the verified deterministic, nonpersistent position-id buffer.
No learned tensor can be dropped, reinitialized, renamed or numerically changed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import time

import torch
from safetensors.torch import load, save

BUFFER = "embeddings.position_ids"
WEIGHTS_SHA256 = "3c9f31665447c8911517620762200d2245a2518d6e7208acc78cd9db317e21ad"
RECIPE = "bge-pinned-position-buffer-v1"
MAX_BYTES = 160_000_000


def validated_parameters(model, original):
    """Prove a single known runtime buffer is the entire inventory difference."""
    state = model.state_dict()
    if (not isinstance(original, dict) or not state or len(original) > 250_000
            or set(original) - set(state) != {BUFFER} or set(state) - set(original)
            or BUFFER in dict(model.named_parameters())):
        raise ValueError("BGE canonicalization requires exactly one nonparameter buffer difference")
    expected = torch.arange(512, dtype=torch.long).unsqueeze(0)
    observed = original[BUFFER]
    runtime = model.get_buffer(BUFFER)
    if (observed.dtype != torch.long or observed.shape != (1, 512)
            or runtime.dtype != torch.long or not torch.equal(observed.cpu(), expected)
            or not torch.equal(runtime.cpu(), expected)):
        raise ValueError("position-id buffer is not the exact deterministic runtime sequence")
    result = {}
    for name, value in state.items():
        source = original[name]
        if (source.dtype != value.dtype or source.shape != value.shape
                or not torch.equal(source.cpu(), value.detach().cpu())
                or not torch.isfinite(source).all()):
            raise ValueError("canonicalization would change a learned tensor: " + name)
        result[name] = source.detach().cpu().contiguous().clone()
    return result


def verify_source_loading(info):
    """The source conversion permits only this declared buffer, never other keys."""
    fields = ("missing_keys", "mismatched_keys", "unexpected_keys", "error_msgs")
    if not isinstance(info, dict) or any(not isinstance(info.get(k), (list, tuple)) for k in fields):
        raise ValueError("missing complete original loading report")
    if (any(info[k] for k in ("missing_keys", "mismatched_keys", "error_msgs"))
            or list(info["unexpected_keys"]) not in ([], [BUFFER])):
        raise ValueError("original BGE load has non-buffer discrepancies")


def canonicalize(snapshot, destination):
    """Preserve the fixed source, derive once, then reload through strict checks."""
    from transformers import AutoModel, AutoTokenizer, __version__ as transformers_version
    from hf_joint_decision_runner import validate_encoder_loading_info, verify_loaded_safetensors
    from model_runner import snapshot_digest
    from public_structural_stage import MODEL_FILES

    if transformers_version != "4.57.3":
        raise ValueError("canonicalization requires the reviewed Transformers 4.57.3 profile")
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    source, destination = Path(snapshot), Path(destination)
    if (source.is_symlink() or not source.is_dir() or destination.exists()
            or destination.is_symlink() or destination.resolve().is_relative_to(source.resolve())
            or {p.name for p in source.iterdir()} != set(MODEL_FILES)):
        raise ValueError("invalid immutable source or create-only derived destination")
    for name in MODEL_FILES:
        item = source / name
        if item.is_symlink() or not item.is_file() or not 0 < item.stat().st_size <= MAX_BYTES:
            raise ValueError("invalid source snapshot member")
    before = snapshot_digest(source)
    payload = (source / "model.safetensors").read_bytes()
    if hashlib.sha256(payload).hexdigest() != WEIGHTS_SHA256:
        raise ValueError("only the fixed published BGE weight SHA is eligible")
    original = load(payload)
    source_model, loading = AutoModel.from_pretrained(
        str(source), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True, torch_dtype=torch.float32)
    verify_source_loading(loading)
    source_model.eval().requires_grad_(False)
    parameters = validated_parameters(source_model, original)
    if snapshot_digest(source) != before:
        raise ValueError("source changed during canonicalization")
    destination.mkdir(parents=False, exist_ok=False)
    for name in MODEL_FILES:
        with (destination / name).open("xb") as stream:
            stream.write(save(parameters, metadata={"format": "pt"}) if name == "model.safetensors"
                         else (source / name).read_bytes())
    derived, derived_info = AutoModel.from_pretrained(
        str(destination), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True, torch_dtype=torch.float32)
    derived.eval().requires_grad_(False)
    verified_load = validate_encoder_loading_info(derived_info)
    verified_values = verify_loaded_safetensors(torch, derived, destination)
    tokenizer = AutoTokenizer.from_pretrained(str(source), local_files_only=True, trust_remote_code=False)
    inputs = tokenizer(["This is a snapshot conversion check.", "A second input checks padding."],
                       return_tensors="pt", padding=True, truncation=False)
    with torch.no_grad():
        old = source_model(**inputs).last_hidden_state
        new = derived(**inputs).last_hidden_state
    if not torch.equal(old, new):
        raise ValueError("source/derived BGE outputs differ")
    if snapshot_digest(source) != before:
        raise ValueError("original publisher bytes changed")
    return {"recipe": RECIPE, "original_snapshot_sha256": before,
            "original_weight_sha256": WEIGHTS_SHA256,
            "derived_snapshot_sha256": snapshot_digest(destination),
            "derived_weight_sha256": hashlib.sha256((destination / "model.safetensors").read_bytes()).hexdigest(),
            "transformers": transformers_version,
            "removed_runtime_buffers": [BUFFER], "removed_buffer_dtype": "int64",
            "removed_buffer_shape": [1, 512], "source_loading_info": loading,
            "preserved_tensor_count": len(parameters), "learned_tensors_unchanged": True,
            "derived_loading": verified_load, "derived_materialization": verified_values,
            "two_input_output_parity": "bit_exact", "cpu_ns": time.process_time_ns() - cpu,
            "wall_ns": time.perf_counter_ns() - start, "production_authorized": False}
