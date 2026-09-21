#!/usr/bin/env python3
"""Independent raw-byte rejection oracle for Platform Types canonical V1."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = json.loads(
    (ROOT / "codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json").read_text(
        encoding="utf-8"
    )
)
DOMAIN = DOC["domain"].encode("utf-8")
MAX_BYTES = DOC["maxEncodedBytes"]
MAX_ITEMS = DOC["maxContainerItems"]
MAX_DEPTH = DOC["maxDepth"]


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, n: int) -> bytes:
        end = self.offset + n
        if end > len(self.data):
            raise ValueError("truncated")
        out = self.data[self.offset:end]
        self.offset = end
        return out

    def n(self, size: int) -> int:
        return int.from_bytes(self.take(size), "big")

    def l16(self) -> bytes:
        return self.take(self.n(2))

    def l32(self) -> bytes:
        return self.take(self.n(4))


def ascii_text(raw: bytes, label: str) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(label) from exc


def valid_module(raw: bytes) -> None:
    value = ascii_text(raw, "module")
    if not value:
        raise ValueError("module")
    for part in value.split("."):
        if (
            not part
            or not part[0].isalnum()
            or not part[-1].isalnum()
            or any(not (ch.islower() or ch.isdigit() or ch in "_-") for ch in part)
        ):
            raise ValueError("module")


def valid_local(raw: bytes) -> None:
    value = ascii_text(raw, "local")
    if (
        not value
        or not value[0].isalnum()
        or not value[-1].isalnum()
        or any(not (ch.islower() or ch.isdigit() or ch in "._-") for ch in value)
    ):
        raise ValueError("local")


def valid_namespaced(raw: bytes) -> None:
    if raw.count(b":") != 1:
        raise ValueError("type id")
    namespace, local = raw.split(b":", 1)
    valid_module(namespace)
    valid_local(local)


def valid_stable(raw: bytes) -> None:
    value = ascii_text(raw, "stable id")
    if not value or any(not (ch.isalnum() or ch in "._-:") for ch in value):
        raise ValueError("stable id")


def valid_label(raw: bytes) -> None:
    value = ascii_text(raw, "label")
    if (
        not value
        or len(raw) > 128
        or not value[0].isalnum()
        or not value[-1].isalnum()
        or any(not (ch.islower() or ch.isdigit() or ch in "._-:") for ch in value)
    ):
        raise ValueError("label")


def validate_value(r: Reader, depth: int = 0) -> None:
    tag = r.n(1)
    if tag == 1:
        if r.n(1) not in (0, 1):
            raise ValueError("invalid bool")
    elif tag == 2:
        r.take(8)
    elif tag == 3:
        r.take(16)
    elif tag == 4:
        r.take(8)
    elif tag == 5:
        r.l32()
    elif tag == 6:
        raw = r.l32()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid text") from exc
        if "\0" in text:
            raise ValueError("NUL text")
    elif tag == 7:
        r.take(32)
    elif tag == 8:
        valid_stable(r.l16())
    elif tag in (9, 10):
        if depth >= MAX_DEPTH:
            raise ValueError("depth")
        count = r.n(4)
        if count > MAX_ITEMS:
            raise ValueError("items")
        previous = None
        for _ in range(count):
            if tag == 10:
                key = r.l16()
                valid_label(key)
                if previous is not None and key <= previous:
                    raise ValueError("map order")
                previous = key
            validate_value(r, depth + 1)
    else:
        raise ValueError("invalid tag")


def validate_raw(raw: bytes) -> None:
    if len(raw) > MAX_BYTES:
        raise ValueError("size")
    r = Reader(raw)
    if r.take(4) != b"HPTC" or r.n(2) != DOC["encodingVersion"]:
        raise ValueError("header")
    if r.l16() != DOMAIN:
        raise ValueError("domain")
    valid_namespaced(r.l16())
    if r.n(4) == 0:
        raise ValueError("schema")
    count = r.n(4)
    if count > MAX_ITEMS:
        raise ValueError("fields")
    previous = None
    for _ in range(count):
        name = r.l16()
        valid_label(name)
        if previous is not None and name <= previous:
            raise ValueError("field order")
        previous = name
        validate_value(r)
    if r.offset != len(raw):
        raise ValueError("trailing")


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def framed16(value: bytes) -> bytes:
    return u16(len(value)) + value


def header(*, schema_version: int, field_count: int) -> bytes:
    return (
        b"HPTC"
        + u16(DOC["encodingVersion"])
        + framed16(DOMAIN)
        + framed16(b"platform.types:negative")
        + u32(schema_version)
        + u32(field_count)
    )


def bool_value(value: int) -> bytes:
    return b"\x01" + bytes([value])


def u64_value(value: int) -> bytes:
    return b"\x02" + value.to_bytes(8, "big")


def rejection_bytes(case: dict) -> bytes:
    kind = case["kind"]
    if kind == "raw_reject":
        return bytes.fromhex(case["encodingHex"])
    if kind == "duplicate_field":
        return (
            header(schema_version=case["schemaVersion"], field_count=2)
            + framed16(b"a")
            + u64_value(1)
            + framed16(b"a")
            + u64_value(2)
        )
    if kind == "duplicate_map_key":
        value = (
            b"\x0a"
            + u32(2)
            + framed16(b"a")
            + bool_value(0)
            + framed16(b"a")
            + bool_value(1)
        )
        return header(schema_version=case["schemaVersion"], field_count=1) + framed16(b"map") + value
    if kind == "zero_schema_version":
        return header(schema_version=0, field_count=0)
    if kind == "oversize_bytes":
        payload = b"\x05" + u32(case["payloadBytes"]) + bytes(case["payloadBytes"])
        return (
            header(schema_version=case["schemaVersion"], field_count=1)
            + framed16(b"payload")
            + payload
        )
    if kind == "depth_overflow":
        value = bool_value(0)
        for _ in range(case["depth"]):
            value = b"\x09" + u32(1) + value
        return (
            header(schema_version=case["schemaVersion"], field_count=1)
            + framed16(b"nested")
            + value
        )
    raise ValueError(f"unknown rejection kind: {kind}")


for case in DOC["rejections"]:
    raw = rejection_bytes(case)
    try:
        validate_raw(raw)
    except ValueError:
        continue
    raise SystemExit(f"{case['id']}: raw-byte rejection oracle accepted invalid bytes")

print(f"platform.types Python raw rejection vectors: {len(DOC['rejections'])} rejected")
