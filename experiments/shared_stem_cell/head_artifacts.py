"""Create-only offline Head candidates, not a second artifact CAS or selector.

Only the existing four CPU Head architectures are decoded. The external manifest
hash AND caller's exact feature/training binding are required on every reopen.
No pickle, import-by-name, callbacks from artifacts, optimizer resume or authority.
"""
from __future__ import annotations

from pathlib import Path
import os

import torch
from safetensors.torch import load, save

from experiments.shared_stem_cell.wire import InputError, canonical, decode, sha, write_once

SCHEMA = "hepta.offline-cell-head.v1"
KINDS = {"linear", "gated", "low_rank", "sparse_expert"}
MAX_WEIGHTS = 64 * 1024**2
MAX_MANIFEST = 65536
BINDING_KEYS = {"scope", "stem_sha256", "dataset_sha256", "feature_profile_sha256",
                "training_lineage_sha256", "logical_cell", "generation"}


def _digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise InputError("exact lowercase SHA256 required")
    return value


def _binding(value):
    if not isinstance(value, dict) or set(value) != BINDING_KEYS:
        raise InputError("complete Head feature/training binding required")
    for key in BINDING_KEYS:
        if key.endswith("sha256"):
            _digest(value[key])
    for key in ("scope", "logical_cell"):
        if not isinstance(value[key], str) or not 1 <= len(value[key].encode()) <= 256:
            raise InputError("bounded Head scope/cell identity required")
    if type(value["generation"]) is not int or not 1 <= value["generation"] < 2**64:
        raise InputError("positive exact candidate generation required")
    return dict(value)


def _shape_count(architecture):
    if not isinstance(architecture, dict) or set(architecture) != {"kind", "width", "classes", "rank"}:
        raise InputError("closed Head architecture required")
    kind, width, classes, rank = (architecture[k] for k in ("kind", "width", "classes", "rank"))
    if (kind not in KINDS or type(width) is not int or not 1 <= width <= 8192
            or type(classes) is not int or not 2 <= classes <= 256
            or type(rank) is not int or not 1 <= rank <= min(256, width)):
        raise InputError("bounded Head architecture required")
    count = (width + 1) * classes
    if kind in {"low_rank", "gated"}:
        count += (width + 1) * rank + rank * classes
    if kind == "gated":
        count += (width + 1) * classes
    if kind == "sparse_expert":
        count += 2 * (width + 1) * classes + 2 * (width + 1)
    if 4 * count > MAX_WEIGHTS - MAX_MANIFEST:
        raise InputError("Head weight allocation budget exceeded")
    return count


def _path(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise InputError("linked Head artifact path")
    return path


def _read(path, maximum):
    path = _path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise InputError("missing/oversized Head artifact")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise InputError("Head artifact byte budget")
    return raw


def _sync_directory(path):
    # Linux research qualification; this is not a portable product durability claim.
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def export_head(directory, model, binding):
    """Export actual parameter tensors; publish the complete manifest LAST."""
    from experiments.shared_stem_cell.execution import Head, parameters

    binding = _binding(binding)
    if type(model) is not Head:
        raise InputError("only the existing concrete Head type is exportable")
    architecture = {"kind": model.kind, "width": model.base.in_features,
                    "classes": model.base.out_features,
                    "rank": model.down.out_features if hasattr(model, "down") else 1}
    count = _shape_count(architecture)
    before = parameters(model)
    state = model.state_dict()
    if before["parameters"] != count:
        raise InputError("Head architecture parameter count drift")
    tensors = {}
    for key, value in state.items():
        if (value.device.type != "cpu" or value.dtype != torch.float32
                or not bool(torch.isfinite(value).all())):
            raise InputError("finite CPU float32 Head tensors required")
        tensors[key] = value.detach().clone().contiguous()
    raw = save(tensors, metadata={"format": "pt"})
    if len(raw) > MAX_WEIGHTS:
        raise InputError("serialized Head byte budget")
    manifest = {"schema": SCHEMA, "architecture": architecture, "binding": binding,
                "weights_sha256": sha(raw), "weights_bytes": len(raw),
                "parameters": before, "producer_sha256": sha(Path(__file__).read_bytes()),
                "optimizer_state_included": False, "production_accepted": False}
    if len(canonical(manifest)) > MAX_MANIFEST:
        raise InputError("Head manifest budget")
    directory = _path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "weights.safetensors").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(directory)
    if parameters(model) != before:
        raise InputError("source Head changed during export")
    manifest_sha = write_once(directory / "manifest.json", manifest)
    _sync_directory(directory)
    return {"manifest_sha256": manifest_sha, "weights_sha256": manifest["weights_sha256"],
            "weights_bytes": len(raw), "parameter_bytes": before["parameter_bytes"],
            "production_accepted": False}


def load_head(directory, expected_manifest_sha256, expected_binding):
    """Decode verified immutable bytes, independent of any model-serving owner."""
    from experiments.shared_stem_cell.execution import Head, parameters

    _digest(expected_manifest_sha256)
    binding = _binding(expected_binding)
    directory = _path(directory)
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != {"manifest.json", "weights.safetensors"}:
        raise InputError("complete exact Head artifact directory required")
    raw = _read(directory / "manifest.json", MAX_MANIFEST)
    if sha(raw) != expected_manifest_sha256:
        raise InputError("external Head manifest digest mismatch")
    manifest = decode(raw)
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "architecture", "binding", "weights_sha256", "weights_bytes", "parameters",
        "producer_sha256", "optimizer_state_included", "production_accepted"
    }:
        raise InputError("closed Head artifact manifest required")
    if (canonical(manifest) != raw or manifest["schema"] != SCHEMA
            or manifest["binding"] != binding or _binding(manifest["binding"]) != binding
            or manifest["optimizer_state_included"] is not False
            or manifest["production_accepted"] is not False):
        raise InputError("Head artifact binding/semantics mismatch")
    _digest(manifest["weights_sha256"])
    _digest(manifest["producer_sha256"])
    count = _shape_count(manifest["architecture"])
    inventory = manifest["parameters"]
    if (not isinstance(inventory, dict) or set(inventory) != {"sha256", "parameters", "parameter_bytes"}
            or type(inventory["parameters"]) is not int or inventory["parameters"] != count
            or type(inventory["parameter_bytes"]) is not int or inventory["parameter_bytes"] != count * 4
            or type(manifest["weights_bytes"]) is not int or not 1 <= manifest["weights_bytes"] <= MAX_WEIGHTS):
        raise InputError("Head parameter/storage inventory mismatch")
    _digest(inventory["sha256"])
    weights = _read(directory / "weights.safetensors", MAX_WEIGHTS)
    if len(weights) != manifest["weights_bytes"] or sha(weights) != manifest["weights_sha256"]:
        raise InputError("Head weight bytes changed")
    # Bytes have already been validated; no check-then-reopen of a mutable path.
    tensors = load(weights)
    if (sum(t.numel() for t in tensors.values()) != count
            or any(t.dtype != torch.float32 or not bool(torch.isfinite(t).all()) for t in tensors.values())):
        raise InputError("Head tensor count/dtype/value mismatch")
    architecture = manifest["architecture"]
    # Reconstruction cannot perturb a caller's training RNG stream.
    with torch.random.fork_rng(devices=[]):
        model = Head(architecture["width"], architecture["classes"],
                     architecture["kind"], architecture["rank"])
    expected = model.state_dict()
    if set(tensors) != set(expected) or any(tensors[k].shape != expected[k].shape for k in expected):
        raise InputError("Head tensor key/shape mismatch")
    model.load_state_dict(tensors, strict=True)
    model.eval().requires_grad_(False)
    if parameters(model) != inventory:
        raise InputError("reloaded Head parameter digest mismatch")
    return model
