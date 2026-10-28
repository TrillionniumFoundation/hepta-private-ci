"""Deterministic, uncompressed, non-pickle state envelope; preparation only."""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import struct

import numpy as np

MAGIC = b"HEPTA_BRANCH_PREPARATION_1\n"
MAX_ARRAYS = 4096
MAX_HEADER_BYTES = 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


@dataclass(frozen=True)
class Layout:
    """Shape-only measurement; deliberately cannot be serialized as evidence."""
    dtype: str
    shape: tuple


def _pack(value, measurement):
    arrays, payloads = [], []

    def visit(item):
        if isinstance(item, (np.ndarray, Layout)):
            require(len(arrays) < MAX_ARRAYS, "Envelope has too many arrays")
            dtype, shape = np.dtype(item.dtype), tuple(item.shape)
            require(dtype.kind in "buif" and all(type(n) is int and n >= 0 for n in shape), "Unsupported array layout")
            size = math.prod(shape) * dtype.itemsize
            require(measurement or isinstance(item, np.ndarray), "Layout is not actual tensor evidence")
            require(isinstance(item, Layout) or item.flags.c_contiguous, "Arrays must be contiguous")
            raw = None if measurement else item.tobytes(order="C")
            arrays.append({"dtype": dtype.str, "shape": list(shape), "bytes": size,
                           "sha256": "0" * 64 if measurement else hashlib.sha256(raw).hexdigest()})
            payloads.append(raw)
            return ["array", len(arrays) - 1]
        if item is None:
            return ["none"]
        if type(item) is bool:
            return ["bool", item]
        if type(item) is int:
            return ["int", str(item)]
        if type(item) is float:
            return ["float64", struct.pack(">d", item).hex()]
        if type(item) is str:
            return ["str", item]
        if type(item) in (list, tuple):
            return ["list" if type(item) is list else "tuple", [visit(v) for v in item]]
        if type(item) is dict:
            require(all(type(k) in (str, int) for k in item), "Mapping keys must be strings or integers")
            keys = sorted(item, key=lambda key: canonical(visit(key)))
            return ["dict", [[visit(key), visit(item[key])] for key in keys]]
        raise ValueError("Unsupported state value: " + type(item).__name__)

    tree = visit(value)
    header = canonical({"tree": tree, "arrays": arrays})
    require(len(header) <= MAX_HEADER_BYTES, "Envelope metadata exceeds format limit")
    return header, arrays, payloads


def measure(value):
    header, arrays, unused = _pack(value, True)
    size = sum(row["bytes"] for row in arrays)
    return {"header_bytes": len(header), "array_payload_bytes": size,
            "file_bytes": len(MAGIC) + 8 + len(header) + size, "array_count": len(arrays),
            "compression_assumed": False}


def dumps(value):
    header, unused, payloads = _pack(value, False)
    return MAGIC + struct.pack(">Q", len(header)) + header + b"".join(payloads)


def digest(value):
    return hashlib.sha256(dumps(value)).hexdigest()


def loads(raw, expected_sha256, maximum_bytes):
    require(type(maximum_bytes) is int and maximum_bytes >= 0, "Artifact cap must be a nonnegative integer")
    require(len(raw) <= maximum_bytes and hashlib.sha256(raw).hexdigest() == expected_sha256, "Envelope identity or size differs")
    require(raw.startswith(MAGIC) and len(raw) >= len(MAGIC) + 8, "Invalid envelope header")
    length = struct.unpack(">Q", raw[len(MAGIC):len(MAGIC) + 8])[0]
    offset = len(MAGIC) + 8 + length
    require(length <= MAX_HEADER_BYTES and offset <= len(raw), "Invalid metadata length")
    header = json.loads(raw[len(MAGIC) + 8:offset])
    require(set(header) == {"tree", "arrays"} and len(header["arrays"]) <= MAX_ARRAYS, "Invalid envelope inventory")
    arrays, used = [], []
    for row in header["arrays"]:
        dtype, shape = np.dtype(row["dtype"]), tuple(row["shape"])
        require(dtype.kind in "buif" and all(type(n) is int and n >= 0 for n in shape), "Invalid array layout")
        size = math.prod(shape) * dtype.itemsize
        block = raw[offset:offset + size]
        require(size == row["bytes"] and len(block) == size and hashlib.sha256(block).hexdigest() == row["sha256"], "Array bytes differ")
        arrays.append(np.frombuffer(block, dtype=dtype).reshape(shape).copy())
        offset += size
    require(offset == len(raw), "Trailing or missing envelope bytes")

    def visit(node):
        tag = node[0]
        if tag == "array":
            index = node[1]
            require(type(index) is int and 0 <= index < len(arrays) and index not in used, "Duplicate or invalid array reference")
            used.append(index)
            return arrays[index]
        if tag == "none":
            return None
        if tag == "bool":
            require(type(node[1]) is bool, "Invalid boolean")
            return node[1]
        if tag in ("int", "float64", "str"):
            return int(node[1]) if tag == "int" else struct.unpack(">d", bytes.fromhex(node[1]))[0] if tag == "float64" else node[1]
        if tag in ("list", "tuple"):
            values = [visit(v) for v in node[1]]
            return tuple(values) if tag == "tuple" else values
        require(tag == "dict", "Unknown tree node")
        result = {}
        for key, value in node[1]:
            key = visit(key)
            require(type(key) in (str, int) and key not in result, "Duplicate or invalid mapping key")
            result[key] = visit(value)
        return result

    value = visit(header["tree"])
    require(len(used) == len(arrays) and dumps(value) == raw, "Noncanonical or unused envelope data")
    return value


def save(path, value, maximum_bytes):
    require(type(maximum_bytes) is int and maximum_bytes >= 0, "Artifact cap must be a nonnegative integer")
    raw = dumps(value)
    require(len(raw) <= maximum_bytes, "Serialization exceeds artifact cap")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
