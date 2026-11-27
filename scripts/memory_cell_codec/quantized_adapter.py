"""Bounded deterministic research codec; decoded tensors remain float32."""

import hashlib
import json
import math
import struct

import numpy as np
import torch

from native import digest
from tensor_contract import MAX_ADAPTER_BYTES, strict_json, tensor_layout

MAGIC = b"HEPTAQ01"
MAX_HEADER_BYTES = 2 * 1024 * 1024
MAX_PACKED_BYTES = MAX_ADAPTER_BYTES + MAX_HEADER_BYTES + 16


def canonical_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def state_digest(state):
    """Same state identity as SourceMemoryCell, distinct from file identity."""
    result = hashlib.sha256()
    for name, value in sorted(state.items()):
        tensor = value.detach().cpu().contiguous()
        result.update(digest((name, list(tensor.shape), str(tensor.dtype))).encode())
        result.update(tensor.view(torch.uint8).numpy().tobytes())
    return result.hexdigest()


def _inventory(layout):
    if type(layout) is not dict or not 1 <= len(layout) <= 4096:
        raise ValueError("bounded tensor inventory required")
    count = 0
    for name, spec in layout.items():
        if (
            type(name) is not str
            or not 1 <= len(name.encode()) <= 1024
            or "\0" in name
            or type(spec) is not dict
            or set(spec) != {"shape", "dtype"}
            or spec["dtype"] != "torch.float32"
            or type(spec["shape"]) is not list
            or len(spec["shape"]) != 2
            or any(
                type(n) is not int or not 1 <= n <= MAX_ADAPTER_BYTES // 4
                for n in spec["shape"]
            )
        ):
            raise ValueError("invalid float32 matrix inventory")
        count += math.prod(spec["shape"])
        if count > MAX_ADAPTER_BYTES // 4:
            raise ValueError("decoded parameter byte budget")
    return count


def encode_tensors(state, bits):
    """Return deterministic symmetric int8/int4 bytes and observed error metrics."""
    if type(bits) is not int or bits not in (4, 8):
        raise ValueError("registered quantization width required")
    if type(state) is not dict or any(
        not isinstance(x, torch.Tensor) for x in state.values()
    ):
        raise ValueError("tensor mapping required")
    layout = tensor_layout(state)
    count = _inventory(layout)
    bound = (1 << (bits - 1)) - 1
    chunks, entries, offset = [], [], 0
    for name, tensor in sorted(state.items()):
        array = tensor.detach().cpu().contiguous().numpy().astype(np.float64)
        if not np.isfinite(array).all():
            raise ValueError("nonfinite source tensor")
        maximum = float(np.abs(array).max())
        scale = maximum / bound if maximum else 1.0
        codes = np.rint(array.reshape(-1) / scale).clip(-bound, bound).astype(np.int16)
        if bits == 8:
            chunk = codes.astype(np.int8).tobytes()
        else:
            unsigned = (codes + bound).astype(np.uint8)
            if len(unsigned) % 2:
                unsigned = np.append(unsigned, np.uint8(0))
            chunk = (unsigned[::2] | (unsigned[1::2] << 4)).tobytes()
        entries.append(
            dict(
                name=name,
                shape=layout[name]["shape"],
                scale=scale,
                offset=offset,
                bytes=len(chunk),
            )
        )
        chunks.append(chunk)
        offset += len(chunk)
    header = canonical_bytes(
        dict(
            schema="hepta.quantized-adapter.v1",
            bits=bits,
            decoded_dtype="torch.float32",
            tensors=entries,
        )
    )
    if len(header) > MAX_HEADER_BYTES:
        raise ValueError("codec header byte budget")
    payload = MAGIC + struct.pack("<Q", len(header)) + header + b"".join(chunks)
    decoded = decode_tensors(payload, expected_layout=layout, expected_bits=bits)
    squared, maximum_error = 0.0, 0.0
    for name in state:
        error = state[name].detach().cpu().double() - decoded[name].double()
        squared += float(error.square().sum())
        maximum_error = max(maximum_error, float(error.abs().max()))
    return payload, dict(
        bits=bits,
        scalar_count=count,
        decoded_tensor_bytes=count * 4,
        packed_bytes=len(payload),
        max_absolute_error=maximum_error,
        mean_squared_error=squared / count,
        source_state_sha256=state_digest(state),
        decoded_state_sha256=state_digest(decoded),
    )


def decode_tensors(payload, *, expected_layout, expected_bits=None):
    """Validate bounds/layout before allocation; no executable serialization."""
    _inventory(expected_layout)
    if (
        type(payload) is not bytes
        or not 16 <= len(payload) <= MAX_PACKED_BYTES
        or payload[:8] != MAGIC
    ):
        raise ValueError("invalid packed adapter envelope")
    length = struct.unpack("<Q", payload[8:16])[0]
    if not 1 <= length <= MAX_HEADER_BYTES or 16 + length > len(payload):
        raise ValueError("packed adapter header length")
    header = strict_json(payload[16 : 16 + length])
    if (
        set(header) != {"schema", "bits", "decoded_dtype", "tensors"}
        or header["schema"] != "hepta.quantized-adapter.v1"
        or type(header["bits"]) is not int
        or header["bits"] not in (4, 8)
        or header["decoded_dtype"] != "torch.float32"
        or type(header["tensors"]) is not list
        or len(header["tensors"]) != len(expected_layout)
    ):
        raise ValueError("unregistered codec header")
    if expected_bits is not None and (
        type(expected_bits) is not int or header["bits"] != expected_bits
    ):
        raise ValueError("codec precision identity mismatch")
    body, offset, prepared = payload[16 + length :], 0, []
    bits, bound = header["bits"], (1 << (header["bits"] - 1)) - 1
    for entry, name in zip(header["tensors"], sorted(expected_layout)):
        if type(entry) is not dict or set(entry) != {
            "name",
            "shape",
            "scale",
            "offset",
            "bytes",
        }:
            raise ValueError("invalid tensor entry")
        shape, scale = expected_layout[name]["shape"], entry["scale"]
        count = math.prod(shape)
        size = count if bits == 8 else (count + 1) // 2
        if (
            entry["name"] != name
            or type(entry["shape"]) is not list
            or entry["shape"] != shape
            or any(type(n) is not int for n in entry["shape"])
            or type(entry["offset"]) is not int
            or entry["offset"] != offset
            or type(entry["bytes"]) is not int
            or entry["bytes"] != size
            or type(scale) not in (int, float)
            or not math.isfinite(scale)
            or scale <= 0
            or offset + size > len(body)
        ):
            raise ValueError("tensor layout, scale or contiguous range mismatch")
        prepared.append(
            (name, shape, float(scale), count, body[offset : offset + size])
        )
        offset += size
    if offset != len(body):
        raise ValueError("trailing or unclaimed tensor bytes")
    decoded = {}
    for name, shape, scale, count, chunk in prepared:
        if bits == 8:
            codes = np.frombuffer(chunk, dtype=np.int8).astype(np.int16)
            if (codes == -128).any():
                raise ValueError("reserved int8 code")
        else:
            packed = np.frombuffer(chunk, dtype=np.uint8)
            codes = np.empty(len(packed) * 2, dtype=np.int16)
            codes[::2], codes[1::2] = packed & 15, packed >> 4
            if (codes[:count] > 14).any() or (count % 2 and codes[-1] != 0):
                raise ValueError("reserved int4 code or nonzero padding")
            codes = codes[:count] - bound
        with np.errstate(over="ignore"):
            array = (codes.astype(np.float64) * scale).astype(np.float32)
        if not np.isfinite(array).all():
            raise ValueError("nonfinite decoded tensor")
        decoded[name] = torch.from_numpy(array.reshape(shape).copy())
    return decoded
