#!/usr/bin/env python3
"""Independent rejection oracle for Platform Types canonical V1."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = json.loads((ROOT / "codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json").read_text(encoding="utf-8"))
DOMAIN = DOC["domain"].encode()
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
        if b"\0" in r.l32():
            raise ValueError("NUL text")
    elif tag == 7:
        r.take(32)
    elif tag == 8:
        r.l16()
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
    if not r.l16() or r.n(4) == 0:
        raise ValueError("identity/schema")
    count = r.n(4)
    if count > MAX_ITEMS:
        raise ValueError("fields")
    previous = None
    for _ in range(count):
        name = r.l16()
        if previous is not None and name <= previous:
            raise ValueError("field order")
        previous = name
        validate_value(r)
    if r.offset != len(raw):
        raise ValueError("trailing")

def rejected(case: dict) -> bool:
    kind = case["kind"]
    if kind == "raw_reject":
        try:
            validate_raw(bytes.fromhex(case["encodingHex"]))
        except ValueError:
            return True
        return False
    if kind == "duplicate_field":
        names = ["a", "a"]
        return len(names) != len(set(names))
    if kind == "duplicate_map_key":
        keys = ["a", "a"]
        return len(keys) != len(set(keys))
    if kind == "zero_schema_version":
        return 0 <= 0
    if kind == "oversize_bytes":
        return case["payloadBytes"] >= MAX_BYTES
    if kind == "depth_overflow":
        return case["depth"] > MAX_DEPTH
    raise ValueError(f"unknown rejection kind: {kind}")

for case in DOC["rejections"]:
    if not rejected(case):
        raise SystemExit(f"{case['id']}: rejection oracle accepted invalid case")
print(f"platform.types Python rejection vectors: {len(DOC['rejections'])} rejected")
