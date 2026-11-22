"""Canonical exact N256 checkpoints at fixed index 256."""

from dataclasses import replace
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    AuthenticCheckpoint,
)
from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile128.extended import (
    _fraction_from_pair,
    _fraction_pair,
    decode_extended_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _row_action,
)


SCHEMA = "hcsn-n256-authentic-index256-checkpoint-profile-v1"
BOUNDARY = 256
MAX_CURSOR_BYTES = 8_388_608


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def start_from_index128(
    source_checkpoint, index32_checkpoint, source_payload, parent_payload
):
    """Cold-validate the archived index-128 checkpoint by exact replay."""

    state = decode_extended_checkpoint(
        source_checkpoint, index32_checkpoint, source_payload, parent_payload
    )
    if state.included_index != 128:
        raise NonSubstochasticSignedIntervalError("source is not index 128")
    return state


def advance_to_index256(checkpoint, parent_payload):
    """Advance one validated index-128 checkpoint to index 256."""

    if checkpoint.included_index != 128:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index 128")
    if _sha256(parent_payload) != checkpoint.parent_payload_sha256:
        raise NonSubstochasticSignedIntervalError("checkpoint parent digest mismatch")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if parent.lane != checkpoint.lane:
        raise NonSubstochasticSignedIntervalError("checkpoint lane mismatch")
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    current = checkpoint
    for next_index in range(129, BOUNDARY + 1):
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


def encode_index256(checkpoint):
    """Encode one canonical index-256 checkpoint under the fixed byte cap."""

    if checkpoint.included_index != BOUNDARY:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index 256")
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
            "index-256 checkpoint exceeds byte cap"
        )
    return payload


def decode_index256(
    payload, source_checkpoint, index32_checkpoint, source_payload, parent_payload
):
    """Cold-decode by exact replay from the archived index-128 checkpoint."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid index-256 payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError(
            "invalid index-256 JSON"
        ) from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload or not isinstance(envelope, dict):
        raise NonSubstochasticSignedIntervalError(
            "noncanonical index-256 checkpoint"
        )
    if set(envelope) != {"body", "body_sha256"} or not isinstance(
        envelope["body"], dict
    ):
        raise NonSubstochasticSignedIntervalError(
            "invalid index-256 envelope"
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
    if (
        set(body) != expected
        or body["schema"] != SCHEMA
        or body["included_index"] != BOUNDARY
        or _sha256(_canonical(body)) != envelope["body_sha256"]
        or body["source_payload_sha256"] != _sha256(source_payload)
        or body["parent_payload_sha256"] != _sha256(parent_payload)
    ):
        raise NonSubstochasticSignedIntervalError(
            "index-256 checkpoint binding mismatch"
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
    initial = start_from_index128(
        source_checkpoint, index32_checkpoint, source_payload, parent_payload
    )
    expected_state = advance_to_index256(initial, parent_payload)
    if observed != expected_state:
        raise NonSubstochasticSignedIntervalError(
            "index-256 checkpoint replay mismatch"
        )
    return observed
