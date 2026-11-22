"""Bounded lossless container for canonical authentic checkpoint bytes."""

import hashlib
import json
import lzma
import struct


MAGIC = b"HCSNCPT1"
HEADER = struct.Struct(">8sQQ32s32s")
MAX_COMPACT_BYTES = 8_388_608
MAX_RAW_BYTES = 33_554_432
INDEX256_SCHEMA = "hcsn-n256-authentic-index256-checkpoint-profile-v1"
BODY_FIELDS = {
    "coefficient",
    "exponential_sum",
    "growth_coefficient",
    "included_index",
    "iterate",
    "lane",
    "parent_payload_sha256",
    "partial",
    "schema",
    "source_payload_sha256",
}
FILTERS = [
    {
        "id": lzma.FILTER_LZMA2,
        "dict_size": 8_388_608,
        "lc": 3,
        "lp": 0,
        "pb": 2,
        "mode": lzma.MODE_NORMAL,
        "nice_len": 64,
        "mf": lzma.MF_BT4,
        "depth": 0,
    }
]


class CompactCheckpointError(ValueError):
    """Raised before accepting a malformed or over-budget container."""


def _sha256(raw):
    return hashlib.sha256(raw).digest()


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_canonical_hex_integer(value, allow_negative):
    if not isinstance(value, str) or not value:
        return False
    digits = value
    if value.startswith("-"):
        if not allow_negative:
            return False
        digits = value[1:]
    return bool(digits) and not (len(digits) > 1 and digits.startswith("0")) and all(
        character in "0123456789abcdef" for character in digits
    ) and value != "-0"


def _validate_fraction_pair(pair):
    return (
        isinstance(pair, list)
        and len(pair) == 2
        and _is_canonical_hex_integer(pair[0], True)
        and _is_canonical_hex_integer(pair[1], False)
        and pair[1] != "0"
    )


def inspect_canonical_checkpoint(raw, expected_schema, expected_index):
    """Validate the exact canonical full-state JSON before compression."""

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW_BYTES:
        raise CompactCheckpointError("raw checkpoint byte bound violated")
    if not isinstance(expected_schema, str) or not expected_schema:
        raise CompactCheckpointError("expected schema is invalid")
    if not isinstance(expected_index, int) or expected_index < 0:
        raise CompactCheckpointError("expected index is invalid")
    try:
        envelope = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompactCheckpointError("checkpoint is not ASCII JSON") from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != raw or not isinstance(envelope, dict):
        raise CompactCheckpointError("checkpoint JSON is not canonical")
    if set(envelope) != {"body", "body_sha256"}:
        raise CompactCheckpointError("checkpoint envelope fields differ")
    body = envelope["body"]
    if not isinstance(body, dict) or set(body) != BODY_FIELDS:
        raise CompactCheckpointError("checkpoint body fields differ")
    body_raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        body.get("schema") != expected_schema
        or body.get("included_index") != expected_index
        or envelope.get("body_sha256") != hashlib.sha256(body_raw).hexdigest()
        or not _is_sha256(body.get("source_payload_sha256"))
        or not _is_sha256(body.get("parent_payload_sha256"))
        or not isinstance(body.get("lane"), str)
        or not body["lane"]
    ):
        raise CompactCheckpointError("checkpoint identity binding differs")
    for name in ("coefficient", "exponential_sum", "growth_coefficient"):
        if not _validate_fraction_pair(body[name]):
            raise CompactCheckpointError(f"checkpoint {name} is not canonical")
    iterate = body.get("iterate")
    partial = body.get("partial")
    if (
        not isinstance(iterate, list)
        or not iterate
        or not isinstance(partial, list)
        or len(iterate) != len(partial)
        or not all(_validate_fraction_pair(pair) for pair in iterate)
        or not all(_validate_fraction_pair(pair) for pair in partial)
    ):
        raise CompactCheckpointError("checkpoint vector fractions are not canonical")
    return {
        "schema": body["schema"],
        "included_index": body["included_index"],
        "lane": body["lane"],
        "vector_length": len(iterate),
        "source_payload_sha256": body["source_payload_sha256"],
        "parent_payload_sha256": body["parent_payload_sha256"],
    }


def encode_compact_checkpoint(raw, expected_schema, expected_index):
    """Encode one deterministic XZ/SHA-256 container under the cursor cap."""

    inspect_canonical_checkpoint(raw, expected_schema, expected_index)
    if not lzma.is_check_supported(lzma.CHECK_SHA256):
        raise CompactCheckpointError("XZ SHA-256 check is unavailable")
    compressed = lzma.compress(
        raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256, filters=FILTERS
    )
    payload = HEADER.pack(
        MAGIC, len(raw), len(compressed), _sha256(raw), _sha256(compressed)
    ) + compressed
    if len(payload) > MAX_COMPACT_BYTES:
        raise CompactCheckpointError("compact checkpoint exceeds cursor cap")
    return payload


def decode_compact_checkpoint(payload, expected_schema, expected_index):
    """Decode with compressed and decompressed byte limits before acceptance."""

    if not isinstance(payload, bytes) or not HEADER.size < len(payload) <= MAX_COMPACT_BYTES:
        raise CompactCheckpointError("compact checkpoint byte bound violated")
    magic, raw_bytes, compressed_bytes, raw_sha, compressed_sha = HEADER.unpack(
        payload[: HEADER.size]
    )
    compressed = payload[HEADER.size :]
    if (
        magic != MAGIC
        or compressed_bytes != len(compressed)
        or not 0 < raw_bytes <= MAX_RAW_BYTES
        or _sha256(compressed) != compressed_sha
    ):
        raise CompactCheckpointError("compact checkpoint header differs")
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    try:
        raw = decompressor.decompress(compressed, max_length=MAX_RAW_BYTES + 1)
    except lzma.LZMAError as error:
        raise CompactCheckpointError("compact checkpoint XZ stream is invalid") from error
    if (
        len(raw) > MAX_RAW_BYTES
        or not decompressor.eof
        or decompressor.unused_data
        or len(raw) != raw_bytes
        or _sha256(raw) != raw_sha
    ):
        raise CompactCheckpointError("compact checkpoint raw binding differs")
    inspect_canonical_checkpoint(raw, expected_schema, expected_index)
    return raw
