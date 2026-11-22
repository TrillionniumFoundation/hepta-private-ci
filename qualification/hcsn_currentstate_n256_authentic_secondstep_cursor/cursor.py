"""Cold-resume an authentic first-step cursor for exactly one more row action.

The parent payload is embedded byte-for-byte in the new canonical envelope.  A
decoder reconstructs and validates that parent and the exact scalar recurrence,
but deliberately does not execute another row action.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    AuthenticFirstStepCursor,
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _product_interval,
    _round_fraction,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-signed-secondstep-cursor-v1"
MAX_CURSOR_BYTES = 4_194_304


@dataclass(frozen=True)
class AuthenticSecondStepCursor:
    """Complete exact state immediately after recurrence index two is added."""

    parent_payload: bytes
    lane: str
    included_index: int
    iterate: tuple[Fraction, ...]
    coefficient: Fraction
    growth_coefficient: Fraction
    exponential_sum: Fraction
    partial: tuple[Fraction, ...]


def _original_vector(cursor):
    """Rebuild the frozen request without performing recurrence work."""

    from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
        build_initial_capsule,
    )

    capsule = build_initial_capsule(
        cursor.lane, cursor.rows_hex, [cursor.vector_hex], cursor.duration_hex
    )
    return capsule.parsed_vectors[0]


def _tail_is_unique(cursor):
    """Apply the frozen exact ratio-bound uniqueness test at index one."""

    argument = cursor.rate * cursor.duration
    tail_argument = argument * cursor.transition_l1_norm
    denominator = cursor.included_index + 1
    ratio_denominator = cursor.included_index + 2
    if argument >= ratio_denominator or tail_argument >= ratio_denominator:
        return False
    next_coefficient = cursor.coefficient * argument / denominator
    next_growth = cursor.growth_coefficient * tail_argument / denominator
    exponential_tail = next_coefficient / (1 - argument / ratio_denominator)
    exp_positive_lower = cursor.exponential_sum
    exp_positive_upper = cursor.exponential_sum + exponential_tail
    exp_negative_lower = 1 / exp_positive_upper
    exp_negative_upper = 1 / exp_positive_lower
    growth_tail = next_growth / (1 - tail_argument / ratio_denominator)
    total_variation = sum(
        (abs(value) for value in _original_vector(cursor)), Fraction(0)
    )
    remainder = total_variation * growth_tail
    for value in cursor.partial:
        lower, upper = _product_interval(
            exp_negative_lower,
            exp_negative_upper,
            value - remainder,
            value + remainder,
        )
        if _round_fraction(lower) != _round_fraction(upper):
            return False
    return True


def build_authentic_secondstep_cursor(parent_payload):
    """Cold-decode one parent, perform one tail check and one row action."""

    parent = decode_authentic_firststep_cursor(parent_payload)
    if parent.included_index != 1:
        raise NonSubstochasticSignedIntervalError(
            "parent is not at first-step boundary"
        )
    if _tail_is_unique(parent):
        raise NonSubstochasticSignedIntervalError(
            "first-step tail already has unique binary64 outputs"
        )
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    denominator = parent.included_index + 1
    coefficient = parent.coefficient * argument / denominator
    growth = parent.growth_coefficient * tail_argument / denominator
    iterate = _row_action(parent.iterate, parent.transition)
    return AuthenticSecondStepCursor(
        parent_payload=parent_payload,
        lane=parent.lane,
        included_index=2,
        iterate=iterate,
        coefficient=coefficient,
        growth_coefficient=growth,
        exponential_sum=parent.exponential_sum + coefficient,
        partial=tuple(
            left + coefficient * right
            for left, right in zip(parent.partial, iterate, strict=True)
        ),
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


def encode_authentic_secondstep_cursor(cursor):
    """Encode a canonical hash-bound second-step cursor."""

    body = {
        "coefficient": _fraction_pair(cursor.coefficient),
        "exponential_sum": _fraction_pair(cursor.exponential_sum),
        "growth_coefficient": _fraction_pair(cursor.growth_coefficient),
        "included_index": cursor.included_index,
        "iterate": [_fraction_pair(value) for value in cursor.iterate],
        "lane": cursor.lane,
        "parent_payload_ascii": cursor.parent_payload.decode("ascii"),
        "parent_payload_sha256": hashlib.sha256(cursor.parent_payload).hexdigest(),
        "partial": [_fraction_pair(value) for value in cursor.partial],
        "schema": SCHEMA,
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
        raise NonSubstochasticSignedIntervalError("second-step cursor exceeds byte cap")
    return payload


def decode_authentic_secondstep_cursor(payload):
    """Cold-decode without performing another tail check or row action."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid second-step cursor payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError(
            "invalid second-step cursor JSON"
        ) from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError("noncanonical second-step cursor")
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError("invalid second-step envelope")
    body = envelope["body"]
    expected = {
        "coefficient",
        "exponential_sum",
        "growth_coefficient",
        "included_index",
        "iterate",
        "lane",
        "parent_payload_ascii",
        "parent_payload_sha256",
        "partial",
        "schema",
    }
    if set(body) != expected:
        raise NonSubstochasticSignedIntervalError("invalid second-step body")
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        body["schema"] != SCHEMA
        or hashlib.sha256(body_bytes).hexdigest() != envelope["body_sha256"]
        or body["included_index"] != 2
    ):
        raise NonSubstochasticSignedIntervalError("second-step cursor digest mismatch")
    try:
        parent_payload = body["parent_payload_ascii"].encode("ascii")
    except (AttributeError, UnicodeEncodeError) as error:
        raise NonSubstochasticSignedIntervalError(
            "invalid embedded parent payload"
        ) from error
    if hashlib.sha256(parent_payload).hexdigest() != body["parent_payload_sha256"]:
        raise NonSubstochasticSignedIntervalError("embedded parent digest mismatch")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if body["lane"] != parent.lane:
        raise NonSubstochasticSignedIntervalError("second-step lane mismatch")
    iterate = tuple(_fraction_from_pair(value, "iterate") for value in body["iterate"])
    partial = tuple(_fraction_from_pair(value, "partial") for value in body["partial"])
    if len(iterate) != len(parent.iterate) or len(partial) != len(parent.partial):
        raise NonSubstochasticSignedIntervalError("second-step dimension mismatch")
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    coefficient = _fraction_from_pair(body["coefficient"], "coefficient")
    growth = _fraction_from_pair(body["growth_coefficient"], "growth coefficient")
    exponential = _fraction_from_pair(body["exponential_sum"], "exponential sum")
    expected_coefficient = parent.coefficient * argument / 2
    if (
        coefficient != expected_coefficient
        or growth != parent.growth_coefficient * tail_argument / 2
        or exponential != parent.exponential_sum + coefficient
        or partial
        != tuple(
            left + coefficient * right
            for left, right in zip(parent.partial, iterate, strict=True)
        )
    ):
        raise NonSubstochasticSignedIntervalError("second-step cursor algebra mismatch")
    return AuthenticSecondStepCursor(
        parent_payload=parent_payload,
        lane=parent.lane,
        included_index=2,
        iterate=iterate,
        coefficient=coefficient,
        growth_coefficient=growth,
        exponential_sum=exponential,
        partial=partial,
    )
