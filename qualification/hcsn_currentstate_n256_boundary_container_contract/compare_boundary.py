"""Independent exact comparator for two fixed N256 boundary containers."""

import hashlib
import struct


MAGIC = b"HCSNBND1"
EXPECTED = (
    ("extended_generator", (257, 257)),
    ("initial", (5, 257)),
    ("lower_selector", (257, 1)),
    ("discounted_selectors", (257, 2)),
)
TOTAL = 68105


def _take(data, offset, count):
    end = offset + count
    if end > len(data):
        raise ValueError("truncated independent parse")
    return data[offset:end], end


def _parse(data):
    data = bytes(data)
    if len(data) < 52:
        raise ValueError("short independent container")
    body, final_digest = data[:-32], data[-32:]
    if hashlib.sha256(body).digest() != final_digest:
        raise ValueError("independent container digest")
    preamble, offset = _take(body, 0, 20)
    if struct.unpack("<8sHHQ", preamble) != (MAGIC, 1, 4, TOTAL):
        raise ValueError("independent preamble")
    parsed = []
    seen = set()
    for expected_name, expected_shape in EXPECTED:
        raw, offset = _take(body, offset, 2)
        name_size = struct.unpack("<H", raw)[0]
        raw, offset = _take(body, offset, name_size)
        try:
            name = raw.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("independent name encoding") from error
        if name != expected_name or name in seen:
            raise ValueError("independent section identity or order")
        seen.add(name)
        raw, offset = _take(body, offset, 1)
        rank = raw[0]
        raw, offset = _take(body, offset, rank * 4)
        shape = tuple(value[0] for value in struct.iter_unpack("<I", raw))
        if shape != expected_shape:
            raise ValueError("independent shape")
        raw, offset = _take(body, offset, 1)
        dtype_size = raw[0]
        dtype, offset = _take(body, offset, dtype_size)
        if dtype != b"<f8":
            raise ValueError("independent dtype/endian")
        raw, offset = _take(body, offset, 8)
        payload_size = struct.unpack("<Q", raw)[0]
        coordinates = 1
        for dimension in shape:
            coordinates *= dimension
        if payload_size != coordinates * 8:
            raise ValueError("independent payload length")
        expected_digest, offset = _take(body, offset, 32)
        payload, offset = _take(body, offset, payload_size)
        if hashlib.sha256(payload).digest() != expected_digest:
            raise ValueError("independent section digest")
        for (bits,) in struct.iter_unpack("<Q", payload):
            if bits & 0x7FF0000000000000 == 0x7FF0000000000000:
                raise ValueError("independent nonfinite payload")
        parsed.append((name, payload))
    if offset != len(body):
        raise ValueError("independent trailing bytes")
    return parsed


def compare_exact(left, right):
    """Require every coordinate byte to match; one mismatch is terminal RED."""
    left_sections = _parse(left)
    right_sections = _parse(right)
    compared = 0
    for (left_name, left_raw), (right_name, right_raw) in zip(
        left_sections, right_sections, strict=True
    ):
        if left_name != right_name or len(left_raw) != len(right_raw):
            raise ValueError("boundary section mismatch")
        for offset in range(0, len(left_raw), 8):
            compared += 1
            if left_raw[offset : offset + 8] != right_raw[offset : offset + 8]:
                raise ValueError(f"boundary mismatch at {left_name}[{offset // 8}]")
    if compared != TOTAL:
        raise ValueError("boundary denominator")
    return {"status": "EXACT", "coordinates_compared": compared, "mismatches": 0}
