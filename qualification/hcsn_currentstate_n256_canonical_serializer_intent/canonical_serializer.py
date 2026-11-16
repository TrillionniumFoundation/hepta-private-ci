"""Canonical byte-exact full-state envelope with fail-closed N256 cold load."""

import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from qualification.hcsn_currentstate_n256_canonical_serializer_intent.admission import require_admission

MAGIC = b"HCSNFSP1"
TRAILER_SIZE = 32
SCHEMA = "hcsn-fullstate-packet-v1"
MAX_NAME_BYTES = 255
MAX_DIMS = 8


@dataclass(frozen=True)
class Block:
    name: str
    dtype: str
    shape: tuple
    payload: bytes


@dataclass(frozen=True)
class Packet:
    identity: str
    generation: int
    origin: int
    target: int
    start: str
    end: str
    alpha: bytes
    operator: bytes


@dataclass(frozen=True)
class Envelope:
    metadata: dict
    blocks: tuple
    packets: tuple


class DecodeError(ValueError):
    """Raised for noncanonical, corrupted, oversized, or trailing bytes."""


def _u32(value):
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("u32 range")
    return struct.pack(">I", value)


def _u64(value):
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("u64 range")
    return struct.pack(">Q", value)


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")


def _take(view, offset, length):
    end = offset + length
    if length < 0 or end > len(view):
        raise DecodeError("truncated packet")
    return bytes(view[offset:end]), end


def _read_u32(view, offset):
    raw, offset = _take(view, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def _read_u64(view, offset):
    raw, offset = _take(view, offset, 8)
    return struct.unpack(">Q", raw)[0], offset


def _validated_block(block):
    name = block.name.encode("ascii")
    if not name or len(name) > MAX_NAME_BYTES:
        raise ValueError("canonical block name")
    if block.dtype != "<f8":
        raise ValueError("only canonical little-endian FP64 blocks are admitted")
    if not block.shape or len(block.shape) > MAX_DIMS or any(not isinstance(size, int) or size <= 0 for size in block.shape):
        raise ValueError("canonical positive shape")
    elements = 1
    for size in block.shape:
        elements *= size
    if elements * 8 != len(block.payload):
        raise ValueError("FP64 payload length mismatch")
    return name


def _packet_metadata(packet):
    if packet.generation < 0 or packet.origin < 0 or packet.target < 0:
        raise ValueError("packet integer range")
    return {
        "identity": packet.identity,
        "generation": packet.generation,
        "origin": packet.origin,
        "target": packet.target,
        "start": packet.start,
        "end": packet.end,
    }


def encode(envelope):
    metadata = dict(envelope.metadata)
    metadata["schema"] = SCHEMA
    metadata_bytes = _canonical_json(metadata)
    names = [_validated_block(block) for block in envelope.blocks]
    if names != sorted(names) or len(set(names)) != len(names):
        raise ValueError("blocks must be unique canonical name order")
    packet_ids = [packet.identity for packet in envelope.packets]
    if packet_ids != sorted(packet_ids) or len(set(packet_ids)) != len(packet_ids):
        raise ValueError("packets must be unique canonical identity order")
    body = bytearray(MAGIC)
    body += _u32(len(metadata_bytes)) + metadata_bytes
    body += _u32(len(envelope.blocks))
    for name, block in zip(names, envelope.blocks):
        dtype = block.dtype.encode("ascii")
        body += _u32(len(name)) + name
        body += _u32(len(dtype)) + dtype
        body += _u32(len(block.shape))
        for size in block.shape:
            body += _u64(size)
        body += _u64(len(block.payload)) + block.payload
    body += _u32(len(envelope.packets))
    for packet in envelope.packets:
        packet_metadata = _canonical_json(_packet_metadata(packet))
        body += _u32(len(packet_metadata)) + packet_metadata
        body += _u64(len(packet.alpha)) + packet.alpha
        body += _u64(len(packet.operator)) + packet.operator
    body += hashlib.sha256(body).digest()
    return bytes(body)


def decode(payload, max_packet_bytes):
    if len(payload) > max_packet_bytes:
        raise DecodeError("packet exceeds frozen allocation")
    if len(payload) < len(MAGIC) + TRAILER_SIZE or payload[: len(MAGIC)] != MAGIC:
        raise DecodeError("packet magic")
    body, trailer = payload[:-TRAILER_SIZE], payload[-TRAILER_SIZE:]
    if hashlib.sha256(body).digest() != trailer:
        raise DecodeError("packet checksum")
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
        name_bytes, offset = _take(view, offset, name_size)
        dtype_size, offset = _read_u32(view, offset)
        dtype_bytes, offset = _take(view, offset, dtype_size)
        dimensions, offset = _read_u32(view, offset)
        if dimensions > MAX_DIMS:
            raise DecodeError("dimension bound")
        shape = []
        for _ in range(dimensions):
            size, offset = _read_u64(view, offset)
            shape.append(size)
        payload_size, offset = _read_u64(view, offset)
        block_payload, offset = _take(view, offset, payload_size)
        block = Block(name_bytes.decode("ascii"), dtype_bytes.decode("ascii"), tuple(shape), block_payload)
        _validated_block(block)
        blocks.append(block)
    packet_count, offset = _read_u32(view, offset)
    packets = []
    for _ in range(packet_count):
        packet_size, offset = _read_u32(view, offset)
        packet_bytes, offset = _take(view, offset, packet_size)
        packet_metadata = json.loads(packet_bytes)
        if _canonical_json(packet_metadata) != packet_bytes:
            raise DecodeError("noncanonical packet metadata")
        alpha_size, offset = _read_u64(view, offset)
        alpha, offset = _take(view, offset, alpha_size)
        operator_size, offset = _read_u64(view, offset)
        operator, offset = _take(view, offset, operator_size)
        packets.append(Packet(alpha=alpha, operator=operator, **packet_metadata))
    if offset != len(view):
        raise DecodeError("trailing bytes")
    envelope = Envelope(metadata, tuple(blocks), tuple(packets))
    if encode(envelope) != payload:
        raise DecodeError("noncanonical byte roundtrip")
    return envelope


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


def cold_load(path, request_path, admission_path):
    admission = require_admission(request_path, admission_path)
    payload = Path(path).read_bytes()
    envelope = decode(payload, admission.max_packet_bytes)
    bindings = envelope.metadata.get("bindings", {})
    expected = {
        "candidate_source_sha256": admission.candidate_source_sha256,
        "oracle_source_sha256": admission.oracle_source_sha256,
        "input_bundle_sha256": admission.input_bundle_sha256,
        "roster_identity": admission.roster_identity,
    }
    if bindings != expected:
        raise DecodeError("full-state binding mismatch")
    return envelope
