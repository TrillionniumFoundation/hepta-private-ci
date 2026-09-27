"""Bounded semantic retrieval wire; data only, never executable authority.

This profile is separate from the existing numeric NeuronFeatureRequestV1.
All integers are big endian. Strings have a u32 byte length; digests are raw
SHA-256 bytes. Request order is bound; prediction order is abstain followed by
source IDs sorted by ASCII. EOF/trailing data and noncanonical values reject.
"""
from __future__ import annotations

import hashlib
import re
import struct
from typing import Any

REQUEST_MAGIC = b"HPTARQ\x01\x00"
REPLY_MAGIC = b"HPTARS\x01\x00"
MAX_FRAME = 65536
MAX_INT = 2**63 - 1
REQUEST_FIELDS = frozenset({
    "operation_id", "workspace_id", "generation", "objective_digest",
    "observation_digest", "bundle_digest", "deadline_ms", "query", "sources",
})
SOURCE_FIELDS = frozenset({"source_id", "revision", "content_sha256", "text"})
REPLY_FIELDS = frozenset({
    "request_sha256", "bundle_digest", "prediction_ppm", "input_tokens",
    "output_tokens", "latency_us",
})


class WireError(ValueError):
    """No complete valid inference result is available."""


def _integer(value: int, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise WireError("integer outside semantic retrieval profile")
    return value


def _digest(value: str) -> bytes:
    if (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            or value == "0" * 64):
        raise WireError("invalid SHA-256")
    return bytes.fromhex(value)


def _text(value: str, maximum: int, *, identity: bool = False) -> bytes:
    if not isinstance(value, str):
        raise WireError("expected text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise WireError("invalid Unicode") from error
    if not 1 <= len(raw) <= maximum:
        raise WireError("text outside semantic retrieval profile")
    if identity and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value):
        raise WireError("invalid identity")
    return struct.pack(">I", len(raw)) + raw


class _Reader:
    def __init__(self, raw: bytes, magic: bytes):
        if type(raw) is not bytes or not len(magic) <= len(raw) <= MAX_FRAME:
            raise WireError("frame outside byte budget")
        self.raw = raw
        self.offset = 0
        if self.take(len(magic)) != magic:
            raise WireError("wrong wire profile or version")

    def take(self, count: int) -> bytes:
        end = self.offset + count
        if end > len(self.raw):
            raise WireError("truncated frame")
        value = self.raw[self.offset:end]
        self.offset = end
        return value

    def integer(self, width: int, low: int, high: int) -> int:
        return _integer(int.from_bytes(self.take(width), "big"), low, high)

    def text(self, maximum: int, *, identity: bool = False) -> str:
        count = self.integer(4, 1, maximum)
        try:
            value = self.take(count).decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise WireError("invalid UTF-8") from error
        _text(value, maximum, identity=identity)
        return value

    def digest(self) -> str:
        value = self.take(32).hex()
        _digest(value)
        return value

    def finish(self) -> None:
        if self.offset != len(self.raw):
            raise WireError("trailing frame data")


def encode_request(request: dict[str, Any]) -> bytes:
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise WireError("unknown or missing request fields")
    data = bytearray(REQUEST_MAGIC)
    for field in ("operation_id", "workspace_id"):
        data.extend(_text(request[field], 128, identity=True))
    data.extend(struct.pack(">Q", _integer(request["generation"], 1, MAX_INT)))
    for field in ("objective_digest", "observation_digest", "bundle_digest"):
        data.extend(_digest(request[field]))
    data.extend(struct.pack(">Q", _integer(request["deadline_ms"], 1, MAX_INT)))
    data.extend(_text(request["query"], 2048))
    sources = request["sources"]
    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= 15:
        raise WireError("source count outside profile")
    data.extend(struct.pack(">I", len(sources)))
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            raise WireError("unknown or missing source fields")
        data.extend(_text(source["source_id"], 128, identity=True))
        if source["source_id"] in seen:
            raise WireError("duplicate source identity")
        seen.add(source["source_id"])
        data.extend(struct.pack(">Q", _integer(source["revision"], 1, MAX_INT)))
        data.extend(_digest(source["content_sha256"]))
        encoded = _text(source["text"], 2048)
        if hashlib.sha256(encoded[4:]).hexdigest() != source["content_sha256"]:
            raise WireError("source bytes changed")
        data.extend(encoded)
    if len(data) > MAX_FRAME:
        raise WireError("frame outside byte budget")
    return bytes(data)


def decode_request(raw: bytes) -> dict[str, Any]:
    reader = _Reader(raw, REQUEST_MAGIC)
    request = {field: reader.text(128, identity=True)
               for field in ("operation_id", "workspace_id")}
    request["generation"] = reader.integer(8, 1, MAX_INT)
    for field in ("objective_digest", "observation_digest", "bundle_digest"):
        request[field] = reader.digest()
    request["deadline_ms"] = reader.integer(8, 1, MAX_INT)
    request["query"] = reader.text(2048)
    count = reader.integer(4, 1, 15)
    request["sources"] = [{
        "source_id": reader.text(128, identity=True),
        "revision": reader.integer(8, 1, MAX_INT),
        "content_sha256": reader.digest(),
        "text": reader.text(2048),
    } for _ in range(count)]
    reader.finish()
    if encode_request(request) != raw:
        raise WireError("noncanonical request")
    return request


def encode_reply(reply: dict[str, Any]) -> bytes:
    if not isinstance(reply, dict) or set(reply) != REPLY_FIELDS:
        raise WireError("unknown or missing reply fields")
    data = bytearray(REPLY_MAGIC)
    data.extend(_digest(reply["request_sha256"]))
    data.extend(_digest(reply["bundle_digest"]))
    probabilities = reply["prediction_ppm"]
    if not isinstance(probabilities, (list, tuple)) or not 2 <= len(probabilities) <= 16:
        raise WireError("prediction shape outside profile")
    if sum(_integer(value, 0, 1000000) for value in probabilities) != 1000000:
        raise WireError("prediction mass is not normalized")
    data.extend(struct.pack(">I", len(probabilities)))
    for value in probabilities:
        data.extend(struct.pack(">I", value))
    for field, low, high in (("input_tokens", 1, 131072),
                             ("output_tokens", 0, 131072), ("latency_us", 0, MAX_INT)):
        data.extend(struct.pack(">Q", _integer(reply[field], low, high)))
    return bytes(data)


def decode_reply(raw: bytes, request_wire: bytes) -> dict[str, Any]:
    request = decode_request(request_wire)
    reader = _Reader(raw, REPLY_MAGIC)
    reply = {"request_sha256": reader.digest(), "bundle_digest": reader.digest()}
    count = reader.integer(4, 2, 16)
    reply["prediction_ppm"] = [reader.integer(4, 0, 1000000) for _ in range(count)]
    reply["input_tokens"] = reader.integer(8, 1, 131072)
    reply["output_tokens"] = reader.integer(8, 0, 131072)
    reply["latency_us"] = reader.integer(8, 0, MAX_INT)
    reader.finish()
    if (reply["request_sha256"] != hashlib.sha256(request_wire).hexdigest()
            or reply["bundle_digest"] != request["bundle_digest"]
            or count != len(request["sources"]) + 1):
        raise WireError("reply belongs to a different request, bundle or candidate set")
    if encode_reply(reply) != raw:
        raise WireError("noncanonical reply")
    return reply
