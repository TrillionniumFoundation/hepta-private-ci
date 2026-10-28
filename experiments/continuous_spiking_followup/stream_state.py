"""Integrity-checked numeric stream snapshots, bound to exact model state.

The NPZ contains only arrays (allow_pickle=False). SHA-256 detects accidental
changes; it is not an authenticity signature or an authority grant. Optimizer,
training RNG and external task/owner state are deliberately outside this format.
"""

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import torch

from .stream_layers import initial_layers


MAX_STATE_BYTES = 256 * 1024 * 1024


def validate_snapshot(model, expected_digest, snapshot):
    from .streaming import FORMAT, model_digest

    required = {
        "format",
        "model_sha256",
        "config",
        "steps",
        "processed_rows",
        "batch_size",
        "elapsed",
        "layers",
    }
    if set(snapshot) != required or snapshot["format"] != FORMAT:
        raise ValueError("unsupported stream snapshot schema")
    if (
        snapshot["model_sha256"] != expected_digest
        or model_digest(model) != expected_digest
    ):
        raise ValueError("stream snapshot model identity mismatch")
    if snapshot["config"] != model.config:
        raise ValueError("stream snapshot configuration mismatch")
    for field in ("steps", "processed_rows", "batch_size"):
        if type(snapshot[field]) is not int or not 0 <= snapshot[field] < 2**63:
            raise ValueError(f"invalid stream counter: {field}")
    batch, steps = snapshot["batch_size"], snapshot["steps"]
    if snapshot["processed_rows"] < batch * steps or (
        steps == 0 and snapshot["processed_rows"] != 0
    ):
        raise ValueError("inconsistent processed-row count")
    anchor = next(model.parameters())
    elapsed = snapshot["elapsed"]
    if (
        not isinstance(elapsed, torch.Tensor)
        or elapsed.shape != (batch,)
        or elapsed.dtype != torch.float64
        or not bool(torch.isfinite(elapsed).all())
        or bool((elapsed < 0).any())
        or (steps == 0 and bool((elapsed != 0).any()))
    ):
        raise ValueError("invalid elapsed-time state")
    # Build a zero-batch schema: untrusted counters must never allocate a cache.
    template = initial_layers(model, 0)
    if not isinstance(snapshot["layers"], list) or len(snapshot["layers"]) != len(
        template
    ):
        raise ValueError("stream layer count mismatch")
    values, total = [], elapsed.numel() * elapsed.element_size()
    for actual, schema in zip(snapshot["layers"], template, strict=True):
        if not isinstance(actual, dict) or set(actual) != set(schema):
            raise ValueError("stream layer schema mismatch")
        layer = {}
        for name, prototype in schema.items():
            value = actual[name]
            shape = list(prototype.shape)
            shape[0] = batch
            if name in {"key", "value"}:
                shape[2] = steps
            if (
                not isinstance(value, torch.Tensor)
                or list(value.shape) != shape
                or value.dtype != prototype.dtype
                or not bool(torch.isfinite(value).all())
            ):
                raise ValueError(f"invalid stream tensor: {name}")
            total += value.numel() * value.element_size()
            if total > MAX_STATE_BYTES:
                raise ValueError("stream state exceeds the 256 MiB safety limit")
            layer[name] = value.detach().to(anchor.device).clone()
        values.append(layer)
    return elapsed.detach().to(anchor.device).clone(), values


def save_snapshot(snapshot, directory):
    """Create one immutable state directory and return its integrity receipt."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    arrays = {"elapsed": snapshot["elapsed"].detach().cpu().numpy()}
    layer_keys = []
    for index, layer in enumerate(snapshot["layers"]):
        layer_keys.append(sorted(layer))
        for name, value in sorted(layer.items()):
            arrays[f"layer_{index:03d}__{name}"] = value.detach().cpu().numpy()
    payload = directory / "state.npz"
    np.savez_compressed(payload, **arrays)
    metadata = {
        key: value
        for key, value in snapshot.items()
        if key not in {"elapsed", "layers"}
    }
    manifest = {
        "snapshot": metadata,
        "layer_keys": layer_keys,
        "payload_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "payload_bytes": payload.stat().st_size,
        "arrays": {
            name: {
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "bytes": value.nbytes,
                "sha256": hashlib.sha256(value.tobytes()).hexdigest(),
            }
            for name, value in arrays.items()
        },
    }
    pending = directory / "manifest.pending"
    pending.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    pending.replace(directory / "manifest.json")
    return {
        "manifest_sha256": hashlib.sha256(
            (directory / "manifest.json").read_bytes()
        ).hexdigest(),
        "payload_sha256": manifest["payload_sha256"],
        "serialized_bytes": payload.stat().st_size
        + (directory / "manifest.json").stat().st_size,
        "state_tensor_bytes": sum(value.nbytes for value in arrays.values()),
    }


def load_snapshot(directory):
    """Read only an intact complete numeric snapshot; validate model on restore."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    payload = directory / "state.npz"
    if (
        payload.stat().st_size != manifest["payload_bytes"]
        or hashlib.sha256(payload.read_bytes()).hexdigest()
        != manifest["payload_sha256"]
    ):
        raise ValueError("stream payload hash/size mismatch")
    if sum(row["bytes"] for row in manifest["arrays"].values()) > MAX_STATE_BYTES:
        raise ValueError("stream archive exceeds the 256 MiB safety limit")
    with zipfile.ZipFile(payload) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_STATE_BYTES + 65536:
            raise ValueError("stream archive expands beyond the safety limit")
    arrays = {}
    with np.load(payload, allow_pickle=False) as source:
        if set(source.files) != set(manifest["arrays"]):
            raise ValueError("stream array inventory mismatch")
        for name, record in manifest["arrays"].items():
            array = source[name]
            if (
                list(array.shape) != record["shape"]
                or str(array.dtype) != record["dtype"]
                or array.nbytes != record["bytes"]
                or hashlib.sha256(array.tobytes()).hexdigest() != record["sha256"]
            ):
                raise ValueError(f"stream array integrity mismatch: {name}")
            arrays[name] = torch.from_numpy(array.copy())
    snapshot = manifest["snapshot"]
    snapshot["elapsed"] = arrays.pop("elapsed")
    snapshot["layers"] = [
        {name: arrays.pop(f"layer_{index:03d}__{name}") for name in keys}
        for index, keys in enumerate(manifest["layer_keys"])
    ]
    if arrays:
        raise ValueError("stream archive contains unassigned arrays")
    return snapshot
