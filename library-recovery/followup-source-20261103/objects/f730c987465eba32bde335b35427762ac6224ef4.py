"""Read-only Python mirror of the unmodified Rust NeuronTickInputV1 digest.

Source: codex-rs/hepta-neuron/src/runtime_types.rs, verified on the public
hepta-private-ci mirror. This does not validate a production manifest,
final-use grant, selected model, worker, NDU signature, journal, or Witness.
Use this only as a contract preparation / domain separation check.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

Q24 = 1 << 24
LIMIT = 8 * Q24
MAX_INPUT_FEATURES = 512
ZERO_SHA = "0" * 64
FEATURE_DOMAIN = b"hepta.neuron.input-features.q24.v1"
TICK_DOMAIN = b"hepta.neuron.tick-input.v1"
HEX = frozenset("0123456789abcdef")


class DiagnosticBindingError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise DiagnosticBindingError(reason)


def u64(value: int) -> bytes:
    require(type(value) is int and 0 <= value < (1 << 64), "invalid u64")
    return value.to_bytes(8, "big")


def i64(value: int) -> bytes:
    require(type(value) is int and -(1 << 63) <= value < (1 << 63), "invalid i64")
    return value.to_bytes(8, "big", signed=True)


def stable_id(value: str) -> bytes:
    require(type(value) is str and bool(value) and "\0" not in value,
            "invalid diagnostic StableId")
    raw = value.encode("utf-8", errors="strict")
    require(0 < len(raw) <= 2**32 - 1, "invalid ID length")
    return len(raw).to_bytes(4, "big") + raw


def digest_bytes(value: str, *, allow_zero: bool = False) -> bytes:
    require(type(value) is str and len(value) == 64 and set(value) <= HEX,
            "invalid digest shape")
    require(allow_zero or value != ZERO_SHA, "zero digest not admitted")
    return bytes.fromhex(value)


def q24_bytes(features: tuple[int, ...]) -> bytes:
    require(type(features) is tuple and 1 <= len(features) <= MAX_INPUT_FEATURES,
            "feature count violates Neuron V1")
    require(all(type(v) is int and -LIMIT <= v <= LIMIT for v in features),
            "feature Q24 envelope invalid")
    return b"".join(i64(v) for v in features)


def canonical_feature_vector_digest_v1(features: tuple[int, ...]) -> str:
    return hashlib.sha256(FEATURE_DOMAIN + u64(len(features)) + q24_bytes(features)).hexdigest()


@dataclass(frozen=True)
class DiagnosticTick:
    tick_id: str
    subject_id: str
    logical_sequence: int
    monotonic_time_micros: int
    checkpoint_digest: str
    input_feature_digest: str
    feature_vector_q24: tuple[int, ...]
    objective_digest: str
    ndu_snapshot_digest: str
    body_generation: int | None = None
    modulator_digest: str | None = None


def semantic_tick_digest_v1(tick: DiagnosticTick) -> str:
    """Byte-for-byte source-derived shape of Rust NeuronTickInputV1::semantic_digest.

    No inference is executed and the hash is *not* a signed Worker receipt.
    """
    require(type(tick) is DiagnosticTick, "invalid diagnostic tick object")
    require(type(tick.logical_sequence) is int and tick.logical_sequence > 0,
            "invalid logical sequence")
    require(type(tick.monotonic_time_micros) is int and tick.monotonic_time_micros > 0,
            "invalid monotonic time")
    require(tick.logical_sequence != 1 or tick.checkpoint_digest == ZERO_SHA,
            "first tick must have zero checkpoint")
    require(tick.logical_sequence == 1 or tick.checkpoint_digest != ZERO_SHA,
            "subsequent tick requires checkpoint")
    vector = q24_bytes(tick.feature_vector_q24)
    observed_feature_digest = canonical_feature_vector_digest_v1(tick.feature_vector_q24)
    require(tick.input_feature_digest == observed_feature_digest,
            "canonical feature digest mismatch")
    if tick.body_generation is not None:
        u64(tick.body_generation)
    if tick.modulator_digest is not None:
        digest_bytes(tick.modulator_digest)
    blob = bytearray(TICK_DOMAIN)
    blob.extend(stable_id(tick.tick_id))
    blob.extend(stable_id(tick.subject_id))
    blob.extend(u64(tick.logical_sequence))
    blob.extend(u64(tick.monotonic_time_micros))
    for d, allow_zero in (
        (tick.checkpoint_digest, tick.logical_sequence == 1),
        (tick.input_feature_digest, False),
        (tick.objective_digest, False),
        (tick.ndu_snapshot_digest, False),
    ):
        blob.extend(digest_bytes(d, allow_zero=allow_zero))
    if tick.body_generation is None:
        blob.append(0)
    else:
        blob.append(1)
        blob.extend(u64(tick.body_generation))
    if tick.modulator_digest is None:
        blob.append(0)
    else:
        blob.append(1)
        blob.extend(digest_bytes(tick.modulator_digest))
    blob.extend(vector)
    return hashlib.sha256(blob).hexdigest()


def audit_readonly_handoff(tick: DiagnosticTick, *, stem_projected_input_digest: str) -> dict:
    """Report domains separately; never mint a grant or an inference receipt."""
    stem = digest_bytes(stem_projected_input_digest)
    feature = canonical_feature_vector_digest_v1(tick.feature_vector_q24)
    semantic = semantic_tick_digest_v1(tick)
    require(stem.hex() != feature and stem.hex() != semantic,
            "Stem reference cannot stand in for a native semantic digest")
    require(feature != semantic, "distinct feature and tick domains must not collapse")
    return {
        "schema": "hepta.neuron.e0-native-tick-handoff-shadow.v1",
        "stem_projected_input_digest": stem.hex(),
        "neuron_v1_input_feature_digest": feature,
        "neuron_v1_tick_semantic_digest": semantic,
        "neuron_model_request_input_digest": semantic,
        "feature_width": len(tick.feature_vector_q24),
        "diagnostic_only": True,
        "actual_worker_called": False,
        "grant_authenticated": False,
        "model_selected": False,
        "ndu_signature_verified": False,
        "checkpoint_committed": False,
        "independent_witness_confirmed": False,
    }
