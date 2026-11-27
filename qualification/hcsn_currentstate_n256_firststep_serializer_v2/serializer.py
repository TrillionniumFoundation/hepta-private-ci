"""Canonical full-state serializer with explicit packet output tensors.

This module is exercised only with small stdlib fixtures.  It does not read or
construct an N256 state and it contains no execution admission.
"""

import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path


MAGIC = b"HCSNFSP2"
TRAILER_SIZE = 32
SCHEMA = "hcsn-fullstate-packet-v2"
MAX_NAME_BYTES = 255
MAX_DIMS = 8


@dataclass(frozen=True)
class Tensor:
    dtype: str
    shape: tuple
    payload: bytes


@dataclass(frozen=True)
class Block:
    name: str
    tensor: Tensor


@dataclass(frozen=True)
class Packet:
    identity: str
    generation: int
    origin: int
    target: int
    start: str
    end: str
    alpha: Tensor
    generator: Tensor
    output: Tensor


@dataclass(frozen=True)
class Envelope:
    metadata: dict
    blocks: tuple
    packets: tuple


class DecodeError(ValueError):
    """Raised for corrupted, noncanonical, oversized, or incomplete bytes."""


def _canonical_json(value):
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _u32(value):
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("u32 range")
    return struct.pack(">I", value)


def _u64(value):
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("u64 range")
    return struct.pack(">Q", value)


def _take(view, offset, length):
    end = offset + length
    if length < 0 or end > len(view):
        raise DecodeError("truncated envelope")
    return bytes(view[offset:end]), end


def _read_u32(view, offset):
    raw, offset = _take(view, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def _read_u64(view, offset):
    raw, offset = _take(view, offset, 8)
    return struct.unpack(">Q", raw)[0], offset


def _validate_tensor(tensor):
    if tensor.dtype != "<f8":
        raise ValueError("only canonical little-endian FP64 tensors are admitted")
    if (
        not tensor.shape
        or len(tensor.shape) > MAX_DIMS
        or any(type(size) is not int or size <= 0 for size in tensor.shape)
    ):
        raise ValueError("canonical positive tensor shape")
    elements = 1
    for size in tensor.shape:
        elements *= size
    if elements * 8 != len(tensor.payload):
        raise ValueError("FP64 tensor payload length mismatch")
    return elements


def _validate_packet(packet):
    if not packet.identity or packet.identity.encode("ascii").decode("ascii") != packet.identity:
        raise ValueError("canonical packet identity")
    if any(type(value) is not int or value < 0 for value in (packet.generation, packet.origin, packet.target)):
        raise ValueError("packet integer range")
    _validate_tensor(packet.alpha)
    dimension = _validate_tensor(packet.output)
    _validate_tensor(packet.generator)
    if packet.output.shape != (dimension,):
        raise ValueError("packet output must be one-dimensional")
    if packet.generator.shape != (dimension, dimension):
        raise ValueError("packet generator/output dimension mismatch")
    if packet.alpha.shape[-1] != dimension:
        raise ValueError("packet alpha/output dimension mismatch")


def _tensor_bytes(tensor):
    _validate_tensor(tensor)
    body = bytearray(_u32(len(tensor.shape)))
    for size in tensor.shape:
        body += _u64(size)
    body += _u64(len(tensor.payload)) + tensor.payload
    return body


def _decode_tensor(view, offset):
    dimensions, offset = _read_u32(view, offset)
    if not 0 < dimensions <= MAX_DIMS:
        raise DecodeError("dimension bound")
    shape = []
    for _ in range(dimensions):
        size, offset = _read_u64(view, offset)
        shape.append(size)
    payload_size, offset = _read_u64(view, offset)
    payload, offset = _take(view, offset, payload_size)
    tensor = Tensor("<f8", tuple(shape), payload)
    _validate_tensor(tensor)
    return tensor, offset


def _packet_metadata(packet):
    return {
        "end": packet.end,
        "generation": packet.generation,
        "identity": packet.identity,
        "origin": packet.origin,
        "start": packet.start,
        "target": packet.target,
    }


def encode(envelope):
    metadata = dict(envelope.metadata)
    metadata["schema"] = SCHEMA
    names = [block.name.encode("ascii") for block in envelope.blocks]
    if any(not name or len(name) > MAX_NAME_BYTES for name in names):
        raise ValueError("canonical block name")
    if names != sorted(names) or len(set(names)) != len(names):
        raise ValueError("blocks must be unique canonical name order")
    packet_ids = [packet.identity for packet in envelope.packets]
    if packet_ids != sorted(packet_ids) or len(set(packet_ids)) != len(packet_ids):
        raise ValueError("packets must be unique canonical identity order")

    metadata_bytes = _canonical_json(metadata)
    body = bytearray(MAGIC)
    body += _u32(len(metadata_bytes)) + metadata_bytes
    body += _u32(len(envelope.blocks))
    for name, block in zip(names, envelope.blocks):
        body += _u32(len(name)) + name + _tensor_bytes(block.tensor)
    body += _u32(len(envelope.packets))
    for packet in envelope.packets:
        _validate_packet(packet)
        packet_metadata = _canonical_json(_packet_metadata(packet))
        body += _u32(len(packet_metadata)) + packet_metadata
        body += _tensor_bytes(packet.alpha)
        body += _tensor_bytes(packet.generator)
        body += _tensor_bytes(packet.output)
    body += hashlib.sha256(body).digest()
    return bytes(body)


def decode(payload, max_envelope_bytes):
    if len(payload) > max_envelope_bytes:
        raise DecodeError("envelope exceeds frozen allocation")
    if len(payload) < len(MAGIC) + TRAILER_SIZE or payload[: len(MAGIC)] != MAGIC:
        raise DecodeError("envelope magic")
    body, trailer = payload[:-TRAILER_SIZE], payload[-TRAILER_SIZE:]
    if hashlib.sha256(body).digest() != trailer:
        raise DecodeError("envelope checksum")
    view = memoryview(body)
    offset = len(MAGIC)
    metadata_size, offset = _read_u32(view, offset)
    metadata_bytes, offset = _take(view, offset, metadata_size)
    metadata = json.loads(metadata_bytes)
    if _canonical_json(metadata) != metadata_bytes or metadata.get("schema") != SCHEMA:
        raise DecodeError("noncanonical metadata")

    block_count, offset = _read_u32(view, offset)
    blocks = []
    for _ in range(block_count):
        name_size, offset = _read_u32(view, offset)
        name, offset = _take(view, offset, name_size)
        tensor, offset = _decode_tensor(view, offset)
        blocks.append(Block(name.decode("ascii"), tensor))
    packet_count, offset = _read_u32(view, offset)
    packets = []
    for _ in range(packet_count):
        metadata_size, offset = _read_u32(view, offset)
        packet_bytes, offset = _take(view, offset, metadata_size)
        packet_metadata = json.loads(packet_bytes)
        if _canonical_json(packet_metadata) != packet_bytes:
            raise DecodeError("noncanonical packet metadata")
        alpha, offset = _decode_tensor(view, offset)
        generator, offset = _decode_tensor(view, offset)
        output, offset = _decode_tensor(view, offset)
        packet = Packet(alpha=alpha, generator=generator, output=output, **packet_metadata)
        _validate_packet(packet)
        packets.append(packet)
    if offset != len(view):
        raise DecodeError("trailing bytes")
    envelope = Envelope(metadata, tuple(blocks), tuple(packets))
    if encode(envelope) != payload:
        raise DecodeError("noncanonical byte roundtrip")
    return envelope


def coordinate_rows(envelope):
    """Return canonical per-coordinate bytes, including every packet output."""

    rows = []
    for block in envelope.blocks:
        _validate_tensor(block.tensor)
        for index in range(0, len(block.tensor.payload), 8):
            rows.append((f"state/{block.name}", index // 8, block.tensor.payload[index:index + 8]))
    for packet in envelope.packets:
        _validate_packet(packet)
        for field in ("alpha", "generator", "output"):
            tensor = getattr(packet, field)
            for index in range(0, len(tensor.payload), 8):
                rows.append((f"packet/{packet.identity}/{field}", index // 8, tensor.payload[index:index + 8]))
    return tuple(rows)


def coordinate_counts(envelope):
    state = sum(_validate_tensor(block.tensor) for block in envelope.blocks)
    alpha = sum(_validate_tensor(packet.alpha) for packet in envelope.packets)
    generator = sum(_validate_tensor(packet.generator) for packet in envelope.packets)
    output = sum(_validate_tensor(packet.output) for packet in envelope.packets)
    return {
        "state": state,
        "packet_alpha": alpha,
        "packet_generator": generator,
        "packet_output": output,
        "packet": alpha + generator + output,
        "total": state + alpha + generator + output,
    }


def publish_atomic(path, envelope):
    path = Path(path)
    payload = encode(envelope)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(payload).hexdigest()
