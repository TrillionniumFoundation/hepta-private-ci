"""Canonical byte container for a future authentic N256 action boundary."""

import hashlib
import struct


AUTHENTIC_MAGIC = b"HCSNBND1"
VERSION = 1
DTYPE = b"<f8"
SECTION_SPECS = (
    ("extended_generator", (257, 257)),
    ("initial", (5, 257)),
    ("lower_selector", (257, 1)),
    ("discounted_selectors", (257, 2)),
)
COORDINATES = 68105
PREAMBLE = struct.Struct("<8sHHQ")


def _product(shape):
    value = 1
    for item in shape:
        value *= item
    return value


def _finite_binary64(raw):
    if len(raw) % 8:
        raise ValueError("payload is not complete binary64 data")
    for (bits,) in struct.iter_unpack("<Q", raw):
        if bits & 0x7FF0000000000000 == 0x7FF0000000000000:
            raise ValueError("nonfinite binary64 payload")


def _read(data, offset, length):
    end = offset + length
    if length < 0 or end > len(data):
        raise ValueError("truncated boundary container")
    return data[offset:end], end


def encode_boundary(sections):
    """Encode exact little-endian FP64 bytes; no float conversion occurs."""
    expected_names = [name for name, _shape in SECTION_SPECS]
    if list(sections) != expected_names:
        raise ValueError("section order or identity")
    output = bytearray(PREAMBLE.pack(AUTHENTIC_MAGIC, VERSION, len(SECTION_SPECS), COORDINATES))
    for name, shape in SECTION_SPECS:
        raw = bytes(sections[name])
        expected_length = _product(shape) * 8
        if len(raw) != expected_length:
            raise ValueError(f"payload length: {name}")
        _finite_binary64(raw)
        encoded_name = name.encode("ascii")
        output += struct.pack("<H", len(encoded_name)) + encoded_name
        output += struct.pack("<B", len(shape))
        output += b"".join(struct.pack("<I", item) for item in shape)
        output += struct.pack("<B", len(DTYPE)) + DTYPE
        output += struct.pack("<Q", len(raw))
        output += hashlib.sha256(raw).digest()
        output += raw
    output += hashlib.sha256(output).digest()
    return bytes(output)


def decode_boundary(data):
    """Decode the authentic fixed profile without normalizing any payload byte."""
    data = bytes(data)
    if len(data) < PREAMBLE.size + 32:
        raise ValueError("short boundary container")
    body, trailer = data[:-32], data[-32:]
    if hashlib.sha256(body).digest() != trailer:
        raise ValueError("whole-container digest")
    preamble, offset = _read(body, 0, PREAMBLE.size)
    if PREAMBLE.unpack(preamble) != (
        AUTHENTIC_MAGIC,
        VERSION,
        len(SECTION_SPECS),
        COORDINATES,
    ):
        raise ValueError("boundary preamble")
    result = {}
    for expected_name, expected_shape in SECTION_SPECS:
        raw_length, offset = _read(body, offset, 2)
        name_length = struct.unpack("<H", raw_length)[0]
        raw_name, offset = _read(body, offset, name_length)
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("section name encoding") from error
        if name != expected_name or name in result:
            raise ValueError("missing, duplicate, reordered, or extra section")
        raw_rank, offset = _read(body, offset, 1)
        rank = raw_rank[0]
        raw_shape, offset = _read(body, offset, rank * 4)
        shape = tuple(item[0] for item in struct.iter_unpack("<I", raw_shape))
        if shape != expected_shape:
            raise ValueError(f"section shape: {name}")
        raw_dtype_length, offset = _read(body, offset, 1)
        dtype_length = raw_dtype_length[0]
        dtype, offset = _read(body, offset, dtype_length)
        if dtype != DTYPE:
            raise ValueError("dtype or endian")
        raw_payload_length, offset = _read(body, offset, 8)
        payload_length = struct.unpack("<Q", raw_payload_length)[0]
        if payload_length != _product(shape) * 8:
            raise ValueError(f"declared payload length: {name}")
        expected_digest, offset = _read(body, offset, 32)
        payload, offset = _read(body, offset, payload_length)
        if hashlib.sha256(payload).digest() != expected_digest:
            raise ValueError(f"section digest: {name}")
        _finite_binary64(payload)
        result[name] = payload
    if offset != len(body):
        raise ValueError("trailing container bytes")
    return result
