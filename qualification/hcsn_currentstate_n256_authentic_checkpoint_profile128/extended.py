"""Canonical exact N256 checkpoints at fixed indices 64 and 128."""

from dataclasses import replace
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    AuthenticCheckpoint,
    decode_checkpoint as decode_index32_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-index128-checkpoint-profile-hex-v2"
BOUNDARIES = (64, 128)
MAX_CURSOR_BYTES = 8_388_608


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _integer_hex(value):
    sign = "-" if value < 0 else ""
    return sign + format(abs(value), "x")


def _integer_from_hex(text, name):
    if not isinstance(text, str) or not text:
        raise NonSubstochasticSignedIntervalError(f"invalid {name} integer")
    digits = text[1:] if text.startswith("-") else text
    if (
        not digits
        or any(character not in "0123456789abcdef" for character in digits)
        or (len(digits) > 1 and digits.startswith("0"))
        or text == "-0"
    ):
        raise NonSubstochasticSignedIntervalError(
            f"noncanonical {name} integer"
        )
    value = int(text, 16)
    if _integer_hex(value) != text:
        raise NonSubstochasticSignedIntervalError(
            f"noncanonical {name} integer"
        )
    return value


def _fraction_pair(value):
    return [_integer_hex(value.numerator), _integer_hex(value.denominator)]


def _fraction_from_pair(pair, name):
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not all(isinstance(value, str) for value in pair)
    ):
        raise NonSubstochasticSignedIntervalError(f"invalid {name} fraction")
    try:
        value = Fraction(
            _integer_from_hex(pair[0], f"{name} numerator"),
            _integer_from_hex(pair[1], f"{name} denominator"),
        )
    except (ValueError, ZeroDivisionError) as error:
        raise NonSubstochasticSignedIntervalError(f"invalid {name} fraction") from error
    if _fraction_pair(value) != pair:
        raise NonSubstochasticSignedIntervalError(f"noncanonical {name} fraction")
    return value


def start_from_index32(source_checkpoint, source_payload, parent_payload):
    """Replay and validate the archived index-32 state before extending it."""

    state = decode_index32_checkpoint(
        source_checkpoint, source_payload, parent_payload
    )
    if state.included_index != 32:
        raise NonSubstochasticSignedIntervalError("source is not index 32")
    return state


def advance_extended_checkpoint(checkpoint, parent_payload, target_index):
    """Advance an exact validated checkpoint to index 64 or 128."""

    if target_index not in BOUNDARIES or target_index <= checkpoint.included_index:
        raise NonSubstochasticSignedIntervalError(
            "target is not a later extended boundary"
        )
    if _sha256(parent_payload) != checkpoint.parent_payload_sha256:
        raise NonSubstochasticSignedIntervalError("checkpoint parent digest mismatch")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if parent.lane != checkpoint.lane:
        raise NonSubstochasticSignedIntervalError("checkpoint lane mismatch")
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    current = checkpoint
    for next_index in range(current.included_index + 1, target_index + 1):
        coefficient = current.coefficient * argument / next_index
        growth = current.growth_coefficient * tail_argument / next_index
        iterate = _row_action(current.iterate, parent.transition)
        current = replace(
            current,
            included_index=next_index,
            iterate=iterate,
            coefficient=coefficient,
            growth_coefficient=growth,
            exponential_sum=current.exponential_sum + coefficient,
            partial=tuple(
                left + coefficient * right
                for left, right in zip(current.partial, iterate, strict=True)
            ),
        )
    return current


def encode_extended_checkpoint(checkpoint):
    """Encode one canonical index-64 or index-128 checkpoint."""

    if checkpoint.included_index not in BOUNDARIES:
        raise NonSubstochasticSignedIntervalError(
            "checkpoint is not at an extended boundary"
        )
    body = {
        "coefficient": _fraction_pair(checkpoint.coefficient),
        "exponential_sum": _fraction_pair(checkpoint.exponential_sum),
        "growth_coefficient": _fraction_pair(checkpoint.growth_coefficient),
        "included_index": checkpoint.included_index,
        "iterate": [_fraction_pair(value) for value in checkpoint.iterate],
        "lane": checkpoint.lane,
        "parent_payload_sha256": checkpoint.parent_payload_sha256,
        "partial": [_fraction_pair(value) for value in checkpoint.partial],
        "schema": SCHEMA,
        "source_payload_sha256": checkpoint.source_payload_sha256,
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
        raise NonSubstochasticSignedIntervalError(
            "extended checkpoint exceeds byte cap"
        )
    return payload


def decode_extended_checkpoint(
    payload, source_checkpoint, source_payload, parent_payload
):
    """Cold-decode by exact replay from the archived index-32 checkpoint."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError(
            "invalid extended checkpoint payload"
        )
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError(
            "invalid extended checkpoint JSON"
        ) from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError(
            "noncanonical extended checkpoint"
        )
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError(
            "invalid extended checkpoint envelope"
        )
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
        "source_payload_sha256",
    }
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        set(body) != expected
        or body["schema"] != SCHEMA
        or body["included_index"] not in BOUNDARIES
        or _sha256(body_bytes) != envelope["body_sha256"]
        or body["source_payload_sha256"] != _sha256(source_payload)
        or body["parent_payload_sha256"] != _sha256(parent_payload)
    ):
        raise NonSubstochasticSignedIntervalError(
            "extended checkpoint binding mismatch"
        )
    observed = AuthenticCheckpoint(
        source_payload_sha256=body["source_payload_sha256"],
        parent_payload_sha256=body["parent_payload_sha256"],
        lane=body["lane"],
        included_index=body["included_index"],
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
    initial = start_from_index32(
        source_checkpoint, source_payload, parent_payload
    )
    expected_state = advance_extended_checkpoint(
        initial, parent_payload, observed.included_index
    )
    if observed != expected_state:
        raise NonSubstochasticSignedIntervalError(
            "extended checkpoint replay mismatch"
        )
    return observed
