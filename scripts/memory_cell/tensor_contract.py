"""Strict bytes/layout admission for scoped memory adapters.

The caller supplies an already-admitted digest, compatible tensor inventory and
current allowed/revoked roots. Structural validation does not authenticate those
inputs, grant training/distribution rights, or issue production acceptance.
No pickle, remote loader, arbitrary path, implicit fallback or model execution.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch
from safetensors.torch import load

MAX_ADAPTER_BYTES = 64 * 1024 * 1024


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def bounded_read(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise ValueError("candidate symlink is not an admitted immutable file")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if not payload or len(payload) > limit:
        raise ValueError("candidate byte bound")
    return payload


def strict_json(payload: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate candidate field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    value = json.loads(payload, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("candidate object required")
    return value


def tensor_layout(state: dict[str, torch.Tensor]) -> dict:
    return {name: {"shape": list(tensor.shape), "dtype": str(tensor.dtype)}
            for name, tensor in sorted(state.items())}


def validate_tensor_bytes(payload: bytes, *, expected_sha256: str, expected_layout: dict) -> dict[str, torch.Tensor]:
    if not payload or len(payload) > MAX_ADAPTER_BYTES or sha256(payload) != expected_sha256:
        raise ValueError("candidate tensor content binding")
    if not expected_layout or len(expected_layout) > 4096:
        raise ValueError("missing/bounded independently supplied tensor inventory")
    tensors = load(payload)
    if tensor_layout(tensors) != expected_layout:
        raise ValueError("candidate tensor inventory/shape/precision mismatch")
    scalars = 0
    for tensor in tensors.values():
        if tensor.ndim != 2 or tensor.dtype != torch.float32 or not torch.isfinite(tensor).all():
            raise ValueError("unsupported or nonfinite adapter tensor")
        scalars += tensor.numel()
    if not 1 <= scalars <= MAX_ADAPTER_BYTES // 4:
        raise ValueError("adapter parameter budget")
    return tensors


def canonical_config(config: dict) -> dict:
    """Only PEFT's set-valued module selectors and local base locator normalize.

    The base is admitted by its complete byte inventory, never by this path.
    Ordered layer composition and all unknown configuration fields stay exact.
    """
    result = {key: value for key, value in config.items() if key != "base_model_name_or_path"}
    for key in ("target_modules", "exclude_modules"):
        if isinstance(result.get(key), (set, list)):
            values = result[key]
            if any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
                raise ValueError("ambiguous adapter module selector")
            result[key] = sorted(values)
    # Enum members in pinned PEFT inherit str; this produces plain JSON values.
    return strict_json(json.dumps(result, sort_keys=True, allow_nan=False).encode())


def read_candidate(directory: Path, *, expected_manifest_sha256: str, base_identity: str,
                   scope: str, expected_layout: dict, expected_config: dict,
                   allowed_roots: set[str], revoked_roots: set[str]):
    """Load bytes once and validate before any caller-selected model mutation."""
    manifest_bytes = bounded_read(directory / "lineage.json", 256 * 1024)
    if sha256(manifest_bytes) != expected_manifest_sha256:
        raise ValueError("candidate manifest binding")
    manifest = strict_json(manifest_bytes)
    required = {"schema", "base_identity", "scope", "roots", "tensor_layout", "adapter_sha256",
                "config_sha256", "training", "model_install_authority", "production_accepted"}
    if set(manifest) != required or manifest["schema"] != "hepta.memory-lora-candidate.v2":
        raise ValueError("unregistered candidate manifest")
    if manifest["base_identity"] != base_identity or manifest["scope"] != scope:
        raise ValueError("candidate base/scope mismatch")
    roots = manifest["roots"]
    if not isinstance(roots, list) or not 1 <= len(roots) <= 20_000 or any(not isinstance(r, str) or not r or len(r.encode()) > 1024 for r in roots):
        raise ValueError("invalid training-root lineage")
    if len(set(roots)) != len(roots) or not set(roots) <= allowed_roots or set(roots) & revoked_roots:
        raise ValueError("candidate source not permitted or revoked")
    if manifest["model_install_authority"] is not False or manifest["production_accepted"] is not False:
        raise ValueError("candidate cannot self-authorize")
    if manifest["tensor_layout"] != expected_layout:
        raise ValueError("declared inventory differs from consumer layout")
    config_bytes = bounded_read(directory / "adapter_config.json", 64 * 1024)
    config = strict_json(config_bytes)
    if sha256(config_bytes) != manifest["config_sha256"] or canonical_config(config) != canonical_config(expected_config):
        raise ValueError("adapter configuration/order/scaling mismatch")
    tensors = validate_tensor_bytes(bounded_read(directory / "adapter_model.safetensors", MAX_ADAPTER_BYTES),
                                    expected_sha256=manifest["adapter_sha256"], expected_layout=expected_layout)
    return tensors, frozenset(roots), manifest
