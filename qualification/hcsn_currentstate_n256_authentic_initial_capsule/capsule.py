"""Canonical initial-state capsule for bounded signed recurrence inputs.

The capsule records only index-zero inputs.  Decoding re-parses the complete
operator, duration, and vectors and reconstructs the initial transition.  No
tail check, recurrence row action, or provider output is evaluated here.
"""

from dataclasses import dataclass
import hashlib
import json

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _canonical_operator,
    _exact_fraction,
    _transition_rows,
)


SCHEMA = "hcsn-n256-authentic-signed-initial-capsule-v1"
MAX_DIMENSION = 259
MAX_VECTORS = 5
MAX_SPARSE_COORDINATES = 1025
MAX_INPUT_COORDINATES = 2320
MAX_CAPSULE_BYTES = 131_072


@dataclass(frozen=True)
class InitialCapsule:
    """Validated index-zero state reconstructed from one canonical request."""

    lane: str
    rows_hex: tuple
    vectors_hex: tuple
    duration_hex: str
    parsed_vectors: tuple
    transition: tuple
    rate: object
    transition_l1_norm: object
    duration: object


def _freeze_rows(rows_hex):
    if not isinstance(rows_hex, (tuple, list)):
        raise NonSubstochasticSignedIntervalError("operator rows must be a sequence")
    frozen = []
    for row in rows_hex:
        if not isinstance(row, (tuple, list)):
            raise NonSubstochasticSignedIntervalError("operator row must be a sequence")
        frozen.append(tuple(tuple(entry) for entry in row))
    return tuple(frozen)


def build_initial_capsule(lane, rows_hex, vectors_hex, duration_hex):
    """Parse and validate a bounded index-zero request without recurrence."""

    if lane not in {"undiscounted", "discounted", "fixture"}:
        raise NonSubstochasticSignedIntervalError("invalid lane")
    frozen_rows = _freeze_rows(rows_hex)
    if not 1 <= len(frozen_rows) <= MAX_DIMENSION:
        raise NonSubstochasticSignedIntervalError("dimension outside bounded domain")
    sparse_coordinates = sum(len(row) for row in frozen_rows)
    if sparse_coordinates > MAX_SPARSE_COORDINATES:
        raise NonSubstochasticSignedIntervalError("sparse coordinates outside bound")
    if not isinstance(vectors_hex, (tuple, list)):
        raise NonSubstochasticSignedIntervalError("vectors must be a sequence")
    frozen_vectors = tuple(tuple(vector) for vector in vectors_hex)
    if not 1 <= len(frozen_vectors) <= MAX_VECTORS:
        raise NonSubstochasticSignedIntervalError("vector count outside bound")
    if any(len(vector) != len(frozen_rows) for vector in frozen_vectors):
        raise NonSubstochasticSignedIntervalError("vector dimension mismatch")
    if sparse_coordinates + sum(map(len, frozen_vectors)) > MAX_INPUT_COORDINATES:
        raise NonSubstochasticSignedIntervalError("input coordinates outside bound")

    certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        frozen_rows, certificates
    )
    parsed_vectors = tuple(
        tuple(
            _exact_fraction(value, "vector value", certificates) for value in vector
        )
        for vector in frozen_vectors
    )
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise NonSubstochasticSignedIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )
    return InitialCapsule(
        lane=lane,
        rows_hex=frozen_rows,
        vectors_hex=frozen_vectors,
        duration_hex=duration_hex,
        parsed_vectors=parsed_vectors,
        transition=transition,
        rate=rate,
        transition_l1_norm=transition_l1_norm,
        duration=duration,
    )


def encode_initial_capsule(capsule):
    """Encode the canonical request snapshot, not derived recurrence work."""

    body = {
        "duration_hex": capsule.duration_hex,
        "lane": capsule.lane,
        "rows_hex": [
            [[column, value] for column, value in row] for row in capsule.rows_hex
        ],
        "schema": SCHEMA,
        "vectors_hex": [list(vector) for vector in capsule.vectors_hex],
    }
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    payload = json.dumps(
        {"body": body, "body_sha256": hashlib.sha256(body_bytes).hexdigest()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    if len(payload) > MAX_CAPSULE_BYTES:
        raise NonSubstochasticSignedIntervalError("initial capsule exceeds byte cap")
    return payload


def decode_initial_capsule(payload):
    """Decode canonical bytes and fully reconstruct the index-zero state."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CAPSULE_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid initial capsule payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError("invalid initial capsule JSON") from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError("noncanonical initial capsule")
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError("invalid initial capsule envelope")
    body = envelope["body"]
    if set(body) != {"duration_hex", "lane", "rows_hex", "schema", "vectors_hex"}:
        raise NonSubstochasticSignedIntervalError("invalid initial capsule body")
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        body["schema"] != SCHEMA
        or not isinstance(envelope["body_sha256"], str)
        or hashlib.sha256(body_bytes).hexdigest() != envelope["body_sha256"]
    ):
        raise NonSubstochasticSignedIntervalError("initial capsule digest mismatch")
    return build_initial_capsule(
        body["lane"], body["rows_hex"], body["vectors_hex"], body["duration_hex"]
    )
