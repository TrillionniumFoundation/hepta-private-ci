"""Canonical authentic-domain cursor after exactly one recurrence row action.

This candidate accepts an already parsed initial capsule, performs the index-zero
tail check once, requires that the ratio-bound precondition cannot yet hold, and
then applies one exact recurrence row action.  Decoding rebuilds the frozen
request and validates the scalar algebra and canonical state without applying a
second row action.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
    InitialCapsule,
    build_initial_capsule,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-signed-firststep-cursor-v1"
MAX_TERMS = 1024
MAX_CURSOR_BYTES = 2_097_152


@dataclass(frozen=True)
class AuthenticFirstStepCursor:
    """Complete exact state immediately after the first recurrence action."""

    lane: str
    rows_hex: tuple
    vector_hex: tuple[str, ...]
    duration_hex: str
    max_terms: int
    included_index: int
    iterate: tuple[Fraction, ...]
    coefficient: Fraction
    growth_coefficient: Fraction
    exponential_sum: Fraction
    partial: tuple[Fraction, ...]
    transition: tuple
    rate: Fraction
    transition_l1_norm: Fraction
    duration: Fraction


def build_authentic_firststep_cursor(capsule, vector_index, *, max_terms=MAX_TERMS):
    """Perform exactly one non-unique tail check and one row action."""

    if not isinstance(capsule, InitialCapsule):
        raise NonSubstochasticSignedIntervalError("invalid initial capsule")
    if (
        not isinstance(vector_index, int)
        or isinstance(vector_index, bool)
        or not 0 <= vector_index < len(capsule.parsed_vectors)
    ):
        raise NonSubstochasticSignedIntervalError("vector index outside bounded domain")
    if (
        not isinstance(max_terms, int)
        or isinstance(max_terms, bool)
        or not 2 <= max_terms <= MAX_TERMS
    ):
        raise NonSubstochasticSignedIntervalError("max_terms outside bounded domain")

    argument = capsule.rate * capsule.duration
    tail_argument = argument * capsule.transition_l1_norm
    if argument < 2 and tail_argument < 2:
        raise NonSubstochasticSignedIntervalError(
            "index-zero tail check was not proven non-unique by the frozen ratio bound"
        )
    vector = capsule.parsed_vectors[vector_index]
    iterate = _row_action(vector, capsule.transition)
    partial = tuple(
        left + argument * right for left, right in zip(vector, iterate, strict=True)
    )
    return AuthenticFirstStepCursor(
        lane=capsule.lane,
        rows_hex=capsule.rows_hex,
        vector_hex=capsule.vectors_hex[vector_index],
        duration_hex=capsule.duration_hex,
        max_terms=max_terms,
        included_index=1,
        iterate=iterate,
        coefficient=argument,
        growth_coefficient=tail_argument,
        exponential_sum=Fraction(1) + argument,
        partial=partial,
        transition=capsule.transition,
        rate=capsule.rate,
        transition_l1_norm=capsule.transition_l1_norm,
        duration=capsule.duration,
    )


def _fraction_pair(value):
    return [str(value.numerator), str(value.denominator)]


def _fraction_from_pair(pair, name):
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not all(isinstance(value, str) for value in pair)
    ):
        raise NonSubstochasticSignedIntervalError(f"invalid {name} fraction")
    try:
        value = Fraction(int(pair[0]), int(pair[1]))
    except (ValueError, ZeroDivisionError) as error:
        raise NonSubstochasticSignedIntervalError(f"invalid {name} fraction") from error
    if _fraction_pair(value) != pair:
        raise NonSubstochasticSignedIntervalError(f"noncanonical {name} fraction")
    return value


def encode_authentic_firststep_cursor(cursor):
    """Encode a canonical, hash-bound first-step cursor."""

    body = {
        "coefficient": _fraction_pair(cursor.coefficient),
        "duration_hex": cursor.duration_hex,
        "exponential_sum": _fraction_pair(cursor.exponential_sum),
        "growth_coefficient": _fraction_pair(cursor.growth_coefficient),
        "included_index": cursor.included_index,
        "iterate": [_fraction_pair(value) for value in cursor.iterate],
        "lane": cursor.lane,
        "max_terms": cursor.max_terms,
        "partial": [_fraction_pair(value) for value in cursor.partial],
        "rows_hex": [
            [[column, value] for column, value in row] for row in cursor.rows_hex
        ],
        "schema": SCHEMA,
        "vector_hex": list(cursor.vector_hex),
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
    if len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("first-step cursor exceeds byte cap")
    return payload


def decode_authentic_firststep_cursor(payload):
    """Cold-decode one cursor without executing another row action."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid first-step cursor payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError("invalid first-step cursor JSON") from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError("noncanonical first-step cursor")
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError("invalid first-step cursor envelope")
    body = envelope["body"]
    expected = {
        "coefficient",
        "duration_hex",
        "exponential_sum",
        "growth_coefficient",
        "included_index",
        "iterate",
        "lane",
        "max_terms",
        "partial",
        "rows_hex",
        "schema",
        "vector_hex",
    }
    if set(body) != expected:
        raise NonSubstochasticSignedIntervalError("invalid first-step cursor body")
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        body["schema"] != SCHEMA
        or not isinstance(envelope["body_sha256"], str)
        or hashlib.sha256(body_bytes).hexdigest() != envelope["body_sha256"]
    ):
        raise NonSubstochasticSignedIntervalError("first-step cursor digest mismatch")
    if body["included_index"] != 1:
        raise NonSubstochasticSignedIntervalError("cursor is not at first-step boundary")
    max_terms = body["max_terms"]
    if (
        not isinstance(max_terms, int)
        or isinstance(max_terms, bool)
        or not 2 <= max_terms <= MAX_TERMS
    ):
        raise NonSubstochasticSignedIntervalError("max_terms outside bounded domain")

    capsule = build_initial_capsule(
        body["lane"], body["rows_hex"], [body["vector_hex"]], body["duration_hex"]
    )
    coefficient = _fraction_from_pair(body["coefficient"], "coefficient")
    growth = _fraction_from_pair(body["growth_coefficient"], "growth coefficient")
    exponential = _fraction_from_pair(body["exponential_sum"], "exponential sum")
    iterate = tuple(_fraction_from_pair(value, "iterate") for value in body["iterate"])
    partial = tuple(_fraction_from_pair(value, "partial") for value in body["partial"])
    if len(iterate) != len(capsule.parsed_vectors[0]) or len(partial) != len(iterate):
        raise NonSubstochasticSignedIntervalError("first-step cursor dimension mismatch")
    expected_coefficient = capsule.rate * capsule.duration
    if (
        coefficient != expected_coefficient
        or growth != expected_coefficient * capsule.transition_l1_norm
        or exponential != 1 + expected_coefficient
        or partial
        != tuple(
            left + coefficient * right
            for left, right in zip(capsule.parsed_vectors[0], iterate, strict=True)
        )
    ):
        raise NonSubstochasticSignedIntervalError("first-step cursor algebra mismatch")
    return AuthenticFirstStepCursor(
        lane=capsule.lane,
        rows_hex=capsule.rows_hex,
        vector_hex=capsule.vectors_hex[0],
        duration_hex=capsule.duration_hex,
        max_terms=max_terms,
        included_index=1,
        iterate=iterate,
        coefficient=coefficient,
        growth_coefficient=growth,
        exponential_sum=exponential,
        partial=partial,
        transition=capsule.transition,
        rate=capsule.rate,
        transition_l1_norm=capsule.transition_l1_norm,
        duration=capsule.duration,
    )
