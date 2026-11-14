"""Standard-library verifier of bounded, FP32, CPU safetensors checkpoints.

No PyTorch, serializer or model import. Reconstruct the exact existing
group_loop.parameter_digest serialization directly from stored model bytes.
This proves file/digest consistency, NOT how the model was trained or that a
remote inference genuinely used it. Never grants activation or authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct

MAX_ARCHIVE_BYTES = 16_000_000
MAX_HEADER_BYTES = 1_000_000
MAX_TENSORS = 4096
MAX_SHAPE_DIM = 8192



def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field: " + key)
        value[key] = item
    return value


def _illegal_json_constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def _finite_json_float(raw):
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON numeric value")
    return value


def strict_json_loads(value, *, max_bytes):
    """Reject duplicate fields, NaNs/infinity and unbounded source data.

    Hashes alone are not provenance. This parser prevents the observer and
    authoring runtime from interpreting identical JSON bytes differently.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 128_000_000:
        raise ValueError("invalid JSON byte ceiling")
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="strict")
    elif isinstance(value, bytes):
        encoded = value
    else:
        raise ValueError("JSON payload must be UTF-8 text or bytes")
    if not 1 <= len(encoded) <= max_bytes:
        raise ValueError("JSON payload byte ceiling exceeded or empty")
    try:
        return json.loads(encoded, object_pairs_hook=_unique_json_object,
                          parse_constant=_illegal_json_constant,
                          parse_float=_finite_json_float)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("noncanonical JSON structure") from exc


def strict_json_file(path, *, max_bytes=64_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected a non-symlink regular JSON record file")
    if not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("JSON record file outside byte ceiling")
    return strict_json_loads(path.read_bytes(), max_bytes=max_bytes)


def verify_checkpoint_file(path):
    """Return independently recomputed digests and a bounded shape inventory."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("checkpoint must be a non-symlink regular file")
    raw = path.read_bytes()
    if not 16 <= len(raw) <= MAX_ARCHIVE_BYTES:
        raise ValueError("bounded checkpoint archive bytes required")
    header_bytes = int.from_bytes(raw[:8], "little")
    if not 2 <= header_bytes <= MAX_HEADER_BYTES or 8 + header_bytes >= len(raw):
        raise ValueError("invalid or unbounded safetensors header")
    try:
        header = strict_json_loads(raw[8:8 + header_bytes], max_bytes=MAX_HEADER_BYTES)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid checkpoint JSON header") from exc
    if type(header) is not dict:
        raise ValueError("checkpoint tensor inventory required")
    metadata = header.pop("__metadata__", None)
    if metadata is not None and (type(metadata) is not dict or
                                 any(type(k) is not str or type(v) is not str
                                     for k, v in metadata.items())):
        raise ValueError("invalid safetensors metadata")
    if not 1 <= len(header) <= MAX_TENSORS:
        raise ValueError("nonempty bounded checkpoint tensors required")
    body = raw[8 + header_bytes:]
    occupied, digest, inventory = [], hashlib.sha256(), {}
    for name, info in sorted(header.items()):
        if (type(name) is not str or not 1 <= len(name) <= 256
                or type(info) is not dict
                or set(info) != {"dtype", "shape", "data_offsets"}):
            raise ValueError("noncanonical tensor identity")
        dims = info["shape"]
        bounds = info["data_offsets"]
        if (info["dtype"] != "F32" or type(dims) is not list
                or not 1 <= len(dims) <= 4
                or any(type(dim) is not int or not 1 <= dim <= MAX_SHAPE_DIM
                       for dim in dims)):
            raise ValueError("only bounded FP32 CPU tensors are supported")
        if (type(bounds) is not list or len(bounds) != 2
                or any(type(v) is not int for v in bounds)):
            raise ValueError("invalid checkpoint tensor offsets")
        lower, upper = bounds
        if (lower < 0 or upper <= lower or upper > len(body)
                or upper - lower != math.prod(dims) * 4):
            raise ValueError("incomplete, overlapping or incorrect tensor extent")
        occupied.append((lower, upper))
        tensor_bytes = body[lower:upper]
        if any(not math.isfinite(v[0]) for v in struct.iter_unpack("<f", tensor_bytes)):
            raise ValueError("nonfinite trained model weights")
        # Exact canonical identity is the same as group_loop.parameter_digest:
        # sorted name, shape tuple repr, torch dtype repr, little endian FP32.
        digest.update(name.encode())
        digest.update(str(tuple(dims)).encode())
        digest.update(b"torch.float32")
        digest.update(tensor_bytes)
        inventory[name] = dims
    intervals = sorted(occupied)
    if (intervals[0][0] != 0 or intervals[-1][1] != len(body)
            or any(a[1] != b[0] for a, b in zip(intervals, intervals[1:]))):
        raise ValueError("checkpoint bytes do not form a contiguous partition")
    return {
        "schema": "hepta.group.safetensors-independent-check.v1",
        "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
        "model_sha256": digest.hexdigest(),
        "bytes": len(raw), "tensors": inventory,
        "source_model_execution_attested": False,
        "training_history_attested": False,
        "authority": "DENY_ALL",
    }
