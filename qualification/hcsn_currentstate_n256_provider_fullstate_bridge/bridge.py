"""Canonical bounded-memory stream bridge for a future admitted N256 run.

The implementation is standard-library only and performs no provider work by
itself.  It turns an already-produced ordered coordinate iterator into fixed
little-endian FP64 frames while preserving a separate coordinate-identity hash
chain.  The authentic N256 entry is fixed to the published denominator and
cannot be shortened by a caller.
"""

import hashlib
import math
import struct
from dataclasses import dataclass


COORDINATE_DENOMINATOR = 18_225_028
FRAME_COORDINATES = 65_536
FRAME_BYTES = FRAME_COORDINATES * 8
FRAME_COUNT = 279
FINAL_FRAME_COORDINATES = 6_020
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
OPERATOR_ROSTER_SHA256 = "b4f1916f021df7c8d4b0cc8f25e09511a427c49c21e45d1432d7d918cb6f8b20"
SEGMENT_ROSTER_SHA256 = "e619e001e04bb0dcc64cb1be78cc9773381241ac8d8a4171d3d4f1b7041eace9"
PROVIDER_SOURCE_SHA256 = "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2"
SERIALIZER_SOURCE_SHA256 = "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a"
COMPARATOR_SOURCE_SHA256 = "d20bfd4ae57e783d506a571e9a9ecb1deed836a8abbafa6e870f2879595972cf"
EXECUTION_PROTOCOL_REQUEST_SHA256 = "f5676dbfe3197c7ef91604d8ef9c3670e18f38eb603eab4e5e02486261c04bfe"
STREAM_NAMES = ("candidate", "oracle", "reference")
CHECKPOINT_PAIR_NAMES = (
    "warm_saved_state_roundtrip",
    "coarse_saved_state_roundtrip",
    "cold_saved_state_roundtrip",
)


class BridgeError(ValueError):
    """Raised before accepting a malformed frame or incomplete manifest."""


@dataclass(frozen=True)
class StreamFrame:
    index: int
    start_coordinate: int
    coordinate_count: int
    coordinate_identity_sha256: str
    payload_sha256: str
    payload: bytes


@dataclass(frozen=True)
class StreamSummary:
    coordinate_count: int
    frame_count: int
    coordinate_identity_root_sha256: str
    payload_root_sha256: str
    maximum_buffer_bytes: int


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _chain(previous, value):
    return hashlib.sha256(bytes.fromhex(previous) + bytes.fromhex(value)).hexdigest()


def _identity_digest(identity, coordinate_index):
    if not isinstance(identity, str):
        raise BridgeError("coordinate identity must be text")
    raw = identity.encode("ascii")
    if not raw or len(raw) > 255 or b"\x00" in raw:
        raise BridgeError("coordinate identity is not canonical ASCII")
    expected_prefix = f"{coordinate_index:08d}/".encode("ascii")
    if not raw.startswith(expected_prefix):
        raise BridgeError("coordinate identity ordinal is not canonical")
    return hashlib.sha256(struct.pack(">H", len(raw)) + raw).hexdigest()


def _write_stream(records, sink, expected_total, frame_coordinates):
    """Write one ordered stream with at most one frame resident at a time."""

    if not isinstance(expected_total, int) or expected_total <= 0:
        raise BridgeError("expected coordinate count is invalid")
    if not isinstance(frame_coordinates, int) or frame_coordinates <= 0:
        raise BridgeError("frame coordinate bound is invalid")
    if not callable(sink):
        raise BridgeError("frame sink is not callable")
    identity_root = "0" * 64
    payload_root = "0" * 64
    pending_values = []
    pending_identity_root = identity_root
    total = 0
    frames = 0

    def flush():
        nonlocal payload_root, frames, pending_values, pending_identity_root
        if not pending_values:
            return
        payload = struct.pack("<" + "d" * len(pending_values), *pending_values)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        frame = StreamFrame(
            index=frames,
            start_coordinate=total - len(pending_values),
            coordinate_count=len(pending_values),
            coordinate_identity_sha256=pending_identity_root,
            payload_sha256=payload_sha256,
            payload=payload,
        )
        sink(frame)
        payload_root = _chain(payload_root, payload_sha256)
        frames += 1
        pending_values = []

    for identity, raw_value in records:
        if total >= expected_total:
            raise BridgeError("coordinate stream exceeds frozen denominator")
        digest = _identity_digest(identity, total)
        value = float(raw_value)
        if not math.isfinite(value):
            raise BridgeError("coordinate value is non-finite")
        identity_root = _chain(identity_root, digest)
        pending_identity_root = identity_root
        pending_values.append(value)
        total += 1
        if len(pending_values) == frame_coordinates:
            flush()
    flush()
    if total != expected_total:
        raise BridgeError("coordinate stream is shorter than frozen denominator")
    return StreamSummary(
        coordinate_count=total,
        frame_count=frames,
        coordinate_identity_root_sha256=identity_root,
        payload_root_sha256=payload_root,
        maximum_buffer_bytes=frame_coordinates * 8,
    )


def write_n256_stream(records, sink):
    """Write exactly 18,225,028 coordinates in 279 bounded frames."""

    summary = _write_stream(records, sink, COORDINATE_DENOMINATOR, FRAME_COORDINATES)
    if summary.frame_count != FRAME_COUNT or summary.maximum_buffer_bytes != FRAME_BYTES:
        raise BridgeError("N256 frame geometry mismatch")
    return summary


def validate_future_manifest(manifest):
    """Validate a future three-stream result without opening any frame payload."""

    exact = {
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "roster_identity": ROSTER_IDENTITY,
        "operator_roster_sha256": OPERATOR_ROSTER_SHA256,
        "segment_roster_sha256": SEGMENT_ROSTER_SHA256,
        "provider_source_sha256": PROVIDER_SOURCE_SHA256,
        "serializer_source_sha256": SERIALIZER_SOURCE_SHA256,
        "comparator_source_sha256": COMPARATOR_SOURCE_SHA256,
        "execution_protocol_request_sha256": EXECUTION_PROTOCOL_REQUEST_SHA256,
        "coordinate_denominator": COORDINATE_DENOMINATOR,
        "frame_coordinates": FRAME_COORDINATES,
        "frame_count": FRAME_COUNT,
        "final_frame_coordinates": FINAL_FRAME_COORDINATES,
    }
    for name, expected in exact.items():
        if manifest.get(name) != expected:
            raise BridgeError(f"manifest {name} mismatch")
    for name in (
        "execution_freeze_sha256",
        "provider_admission_sha256",
        "certificate_set_sha256",
    ):
        if not _is_sha256(manifest.get(name)):
            raise BridgeError(f"manifest {name} is missing")
    streams = manifest.get("streams")
    if not isinstance(streams, dict) or tuple(sorted(streams)) != tuple(sorted(STREAM_NAMES)):
        raise BridgeError("manifest stream roster mismatch")
    identity_roots = set()
    for name in STREAM_NAMES:
        record = streams[name]
        if (
            record.get("coordinate_count") != COORDINATE_DENOMINATOR
            or record.get("frame_count") != FRAME_COUNT
            or record.get("maximum_buffer_bytes") != FRAME_BYTES
        ):
            raise BridgeError(f"{name} stream geometry mismatch")
        for field in ("coordinate_identity_root_sha256", "payload_root_sha256"):
            if not _is_sha256(record.get(field)):
                raise BridgeError(f"{name} stream {field} is missing")
        identity_roots.add(record["coordinate_identity_root_sha256"])
    if len(identity_roots) != 1:
        raise BridgeError("three streams do not share coordinate identity")
    pairs = manifest.get("byte_exact_pairs")
    if not isinstance(pairs, list) or [item.get("name") for item in pairs] != list(
        CHECKPOINT_PAIR_NAMES
    ):
        raise BridgeError("checkpoint pair roster mismatch")
    for pair in pairs:
        producer = pair.get("producer_sha256")
        restored = pair.get("cold_loader_sha256")
        if not _is_sha256(producer) or producer != restored:
            raise BridgeError(f"{pair.get('name')} is not byte exact")
        if not isinstance(pair.get("bytes"), int) or pair["bytes"] <= 0:
            raise BridgeError(f"{pair.get('name')} byte count is invalid")
    if manifest.get("signed_error_cancellation_used") is not False:
        raise BridgeError("signed error cancellation is forbidden")
    if manifest.get("historical_negative_and_unknown_preserved") is not True:
        raise BridgeError("historical RED or UNKNOWN was erased")
    if manifest.get("largegrid_qualification") is not False:
        raise BridgeError("stream manifest cannot self-grant qualification")
    if manifest.get("production_adoption") is not False:
        raise BridgeError("stream manifest cannot adopt production")
    return True
