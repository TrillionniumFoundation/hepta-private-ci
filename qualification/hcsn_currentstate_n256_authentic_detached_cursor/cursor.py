"""Detach an authentic index-two cursor while preserving exact parent custody.

The #6931 source cursor embeds its complete first-step parent.  This successor
stores only the parent's SHA-256 and requires the exact parent bytes at cold
decode.  Both detachment and cold decode independently recompute the missing
row-action relation.  Neither path advances the recurrence beyond index two.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_secondstep_cursor.cursor import (
    decode_authentic_secondstep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-detached-parent-cursor-v1"
MAX_CURSOR_BYTES = 2_097_152


@dataclass(frozen=True)
class AuthenticDetachedCursor:
    """Exact index-two state whose first-step parent is supplied separately."""

    parent_payload_sha256: str
    lane: str
    included_index: int
    iterate: tuple[Fraction, ...]
    coefficient: Fraction
    growth_coefficient: Fraction
    exponential_sum: Fraction
    partial: tuple[Fraction, ...]


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _expected_state(parent):
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    coefficient = parent.coefficient * argument / 2
    growth = parent.growth_coefficient * tail_argument / 2
    iterate = _row_action(parent.iterate, parent.transition)
    partial = tuple(
        left + coefficient * right
        for left, right in zip(parent.partial, iterate, strict=True)
    )
    return (
        iterate,
        coefficient,
        growth,
        parent.exponential_sum + coefficient,
        partial,
    )


def _require_exact_relation(parent, cursor):
    expected = _expected_state(parent)
    observed = (
        cursor.iterate,
        cursor.coefficient,
        cursor.growth_coefficient,
        cursor.exponential_sum,
        cursor.partial,
    )
    if observed != expected:
        raise NonSubstochasticSignedIntervalError(
            "index-two row-action relation mismatch"
        )


def detach_authentic_secondstep_cursor(secondstep_payload):
    """Validate one embedded-parent source and return a detached index-two state."""

    source = decode_authentic_secondstep_cursor(secondstep_payload)
    parent = decode_authentic_firststep_cursor(source.parent_payload)
    _require_exact_relation(parent, source)
    return AuthenticDetachedCursor(
        parent_payload_sha256=_sha256(source.parent_payload),
        lane=source.lane,
        included_index=source.included_index,
        iterate=source.iterate,
        coefficient=source.coefficient,
        growth_coefficient=source.growth_coefficient,
        exponential_sum=source.exponential_sum,
        partial=source.partial,
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


def encode_authentic_detached_cursor(cursor):
    """Encode a canonical state that binds, but does not embed, its parent."""

    body = {
        "coefficient": _fraction_pair(cursor.coefficient),
        "exponential_sum": _fraction_pair(cursor.exponential_sum),
        "growth_coefficient": _fraction_pair(cursor.growth_coefficient),
        "included_index": cursor.included_index,
        "iterate": [_fraction_pair(value) for value in cursor.iterate],
        "lane": cursor.lane,
        "parent_payload_sha256": cursor.parent_payload_sha256,
        "partial": [_fraction_pair(value) for value in cursor.partial],
        "schema": SCHEMA,
    }
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    payload = json.dumps(
        {"body": body, "body_sha256": _sha256(body_bytes)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    if len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("detached cursor exceeds byte cap")
    return payload


def decode_authentic_detached_cursor(payload, parent_payload):
    """Cold-decode against exact external parent bytes and recompute row action."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid detached cursor payload")
    if not isinstance(parent_payload, bytes):
        raise NonSubstochasticSignedIntervalError("invalid detached parent payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError(
            "invalid detached cursor JSON"
        ) from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError("noncanonical detached cursor")
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError("invalid detached cursor envelope")
    body = envelope["body"]
    expected = {
        "coefficient",
        "exponential_sum",
        "growth_coefficient",
        "included_index",
        "iterate",
        "lane",
        "parent_payload_sha256",
        "partial",
        "schema",
    }
    if set(body) != expected:
        raise NonSubstochasticSignedIntervalError("invalid detached cursor body")
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        body["schema"] != SCHEMA
        or body["included_index"] != 2
        or _sha256(body_bytes) != envelope["body_sha256"]
    ):
        raise NonSubstochasticSignedIntervalError(
            "detached cursor digest or boundary mismatch"
        )
    if _sha256(parent_payload) != body["parent_payload_sha256"]:
        raise NonSubstochasticSignedIntervalError("detached parent digest mismatch")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if body["lane"] != parent.lane:
        raise NonSubstochasticSignedIntervalError("detached cursor lane mismatch")
    cursor = AuthenticDetachedCursor(
        parent_payload_sha256=body["parent_payload_sha256"],
        lane=parent.lane,
        included_index=2,
        iterate=tuple(
            _fraction_from_pair(value, "iterate") for value in body["iterate"]
        ),
        coefficient=_fraction_from_pair(body["coefficient"], "coefficient"),
        growth_coefficient=_fraction_from_pair(
            body["growth_coefficient"], "growth coefficient"
        ),
        exponential_sum=_fraction_from_pair(
            body["exponential_sum"], "exponential sum"
        ),
        partial=tuple(
            _fraction_from_pair(value, "partial") for value in body["partial"]
        ),
    )
    if len(cursor.iterate) != len(parent.iterate) or len(cursor.partial) != len(
        parent.partial
    ):
        raise NonSubstochasticSignedIntervalError("detached cursor dimension mismatch")
    _require_exact_relation(parent, cursor)
    return cursor
