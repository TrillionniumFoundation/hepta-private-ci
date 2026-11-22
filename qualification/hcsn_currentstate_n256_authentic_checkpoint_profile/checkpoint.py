"""Canonical exact checkpoints for fixed authentic N256 recurrence boundaries."""

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_detached_cursor.cursor import (
    decode_authentic_detached_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-index32-checkpoint-profile-v1"
BOUNDARIES = (4, 8, 16, 32)
MAX_CURSOR_BYTES = 8_388_608


@dataclass(frozen=True)
class AuthenticCheckpoint:
    """Exact recurrence state bound to an archived index-two input and parent."""

    source_payload_sha256: str
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


def _from_index_two(source_payload, parent_payload):
    state = decode_authentic_detached_cursor(source_payload, parent_payload)
    return AuthenticCheckpoint(
        source_payload_sha256=_sha256(source_payload),
        parent_payload_sha256=_sha256(parent_payload),
        lane=state.lane,
        included_index=state.included_index,
        iterate=state.iterate,
        coefficient=state.coefficient,
        growth_coefficient=state.growth_coefficient,
        exponential_sum=state.exponential_sum,
        partial=state.partial,
    )


def advance_checkpoint(checkpoint, parent_payload, target_index):
    """Advance exactly to one fixed boundary without evaluating a tail."""

    if target_index not in BOUNDARIES or target_index <= checkpoint.included_index:
        raise NonSubstochasticSignedIntervalError(
            "target is not a later fixed boundary"
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


def encode_checkpoint(checkpoint):
    """Encode a canonical fixed-boundary checkpoint."""

    if checkpoint.included_index not in BOUNDARIES:
        raise NonSubstochasticSignedIntervalError("checkpoint is not at fixed boundary")
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
        raise NonSubstochasticSignedIntervalError("checkpoint exceeds byte cap")
    return payload


def decode_checkpoint(payload, source_payload, parent_payload):
    """Cold-decode by exact replay from the archived index-two state."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid checkpoint payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError("invalid checkpoint JSON") from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError("noncanonical checkpoint")
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError("invalid checkpoint envelope")
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
        raise NonSubstochasticSignedIntervalError("checkpoint binding mismatch")
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
    initial = _from_index_two(source_payload, parent_payload)
    expected_state = advance_checkpoint(
        initial, parent_payload, observed.included_index
    )
    if observed != expected_state:
        raise NonSubstochasticSignedIntervalError("checkpoint replay mismatch")
    return observed


def start_from_index_two(source_payload, parent_payload):
    """Expose the validated archived index-two state to the fixed profile."""

    return _from_index_two(source_payload, parent_payload)
