"""Bounded, lossless checkpoints and machine-readable run records."""

import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def checkpoint_save(model, directory, extra=None):
    """Preserve every state tensor exactly; each blob stays below 400 KB."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    items, buffers, offset = [], [], 0
    for name, tensor in model.state_dict().items():
        array = tensor.detach().cpu().numpy()
        raw = array.tobytes()
        items.append(
            {
                "name": name,
                "shape": list(array.shape),
                "dtype": array.dtype.str,
                "sha256": digest_bytes(raw),
                "offset": offset,
                "nbytes": len(raw),
            }
        )
        buffers.append(raw)
        offset += len(raw)
    packed, parts = b"".join(buffers), []
    for part, start in enumerate(range(0, len(packed), 360000)):
        filename = f"state_{part:03d}.npz"
        path = directory / filename
        np.savez_compressed(
            path, bytes=np.frombuffer(packed[start : start + 360000], dtype=np.uint8)
        )
        parts.append({"file": filename, "sha256": digest_bytes(path.read_bytes())})
    manifest = {
        "format": "concatenated_state_v1",
        "config": model.config,
        "tensors": items,
        "parts": parts,
        "extra": extra or {},
    }
    write_json(directory / "manifest.json", manifest)
    return digest_bytes((directory / "manifest.json").read_bytes())


def checkpoint_load(model, directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["config"] != model.config:
        raise ValueError("checkpoint architecture/configuration mismatch")
    buffers = []
    for part in manifest["parts"]:
        path = directory / part["file"]
        if digest_bytes(path.read_bytes()) != part["sha256"]:
            raise ValueError("checkpoint part hash mismatch")
        with np.load(path, allow_pickle=False) as data:
            buffers.append(data["bytes"].tobytes())
    packed = b"".join(buffers)
    state, expected = {}, model.state_dict()
    for item in manifest["tensors"]:
        raw = packed[item["offset"] : item["offset"] + item["nbytes"]]
        if digest_bytes(raw) != item["sha256"]:
            raise ValueError("checkpoint tensor hash mismatch")
        array = (
            np.frombuffer(raw, dtype=np.dtype(item["dtype"]))
            .reshape(item["shape"])
            .copy()
        )
        state[item["name"]] = torch.from_numpy(array)
        if state[item["name"]].dtype != expected[item["name"]].dtype:
            raise ValueError("checkpoint dtype would be silently converted")
    model.load_state_dict(state, strict=True)
    return manifest


def source_seal(directory, create=False):
    directory = Path(directory)
    seal_path = directory / "SOURCE_SEAL.json"
    records = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if "results" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.is_file() and (
            path.suffix == ".py" or path.name in {"PROTOCOL.json", "requirements.txt"}
        ):
            records[str(relative)] = digest_bytes(path.read_bytes())
    digest = digest_bytes(json.dumps(records, sort_keys=True).encode())
    if create:
        write_json(
            seal_path, {"files": records, "sha256": digest, "created_unix": time.time()}
        )
    elif (
        not seal_path.exists() or json.loads(seal_path.read_text())["sha256"] != digest
    ):
        raise ValueError("scientific source differs from the frozen seal")
    return digest


def environment():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "cuda": torch.cuda.is_available(),
        "threads": torch.get_num_threads(),
        "timing": "process CPU and elapsed wall; CPU is not hardware energy",
    }
