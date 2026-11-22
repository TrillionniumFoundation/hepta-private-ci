"""Exact continuation from authentic index256 state to the first possible tail check."""

from dataclasses import replace
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    AuthenticCheckpoint,
)
from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile128.extended import (
    _fraction_from_pair,
    _fraction_pair,
)
from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    INDEX256_SCHEMA,
    inspect_canonical_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _exact_fraction,
    _product_interval,
    _round_fraction,
    _row_action,
)


TARGET_INDEX = 537
SCHEMA = "hcsn-n256-authentic-index537-tail-checkpoint-v1"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_index256(raw, parent_payload):
    """Parse an already independently archived index256 canonical full state."""

    metadata = inspect_canonical_checkpoint(raw, INDEX256_SCHEMA, 256)
    envelope = json.loads(raw)
    body = envelope["body"]
    if body["parent_payload_sha256"] != _sha256(parent_payload):
        raise NonSubstochasticSignedIntervalError("index256 parent digest mismatch")
    return AuthenticCheckpoint(
        source_payload_sha256=body["source_payload_sha256"],
        parent_payload_sha256=body["parent_payload_sha256"],
        lane=metadata["lane"],
        included_index=256,
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


def advance_to_index537(checkpoint, parent_payload, progress=None):
    """Apply exactly 281 authentic recurrence row actions without a tail check."""

    if checkpoint.included_index != 256:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index256")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if parent.lane != checkpoint.lane:
        raise NonSubstochasticSignedIntervalError("checkpoint lane differs")
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    current = checkpoint
    for next_index in range(257, TARGET_INDEX + 1):
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
        if progress is not None and next_index % 8 == 0:
            progress(next_index)
    return current


def first_tail_check(checkpoint, parent_payload):
    """Evaluate exactly one ratio-bound interval at included index537."""

    if checkpoint.included_index != TARGET_INDEX:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index537")
    parent = decode_authentic_firststep_cursor(parent_payload)
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    denominator = checkpoint.included_index + 1
    ratio_denominator = checkpoint.included_index + 2
    if argument >= ratio_denominator or tail_argument >= ratio_denominator:
        raise NonSubstochasticSignedIntervalError(
            "index537 ratio-bound precondition is not satisfied"
        )
    next_coefficient = checkpoint.coefficient * argument / denominator
    next_growth = checkpoint.growth_coefficient * tail_argument / denominator
    exponential_tail = next_coefficient / (1 - argument / ratio_denominator)
    exp_positive_lower = checkpoint.exponential_sum
    exp_positive_upper = checkpoint.exponential_sum + exponential_tail
    exp_negative_lower = 1 / exp_positive_upper
    exp_negative_upper = 1 / exp_positive_lower
    growth_tail = next_growth / (1 - tail_argument / ratio_denominator)
    conversions = []
    vector = tuple(
        _exact_fraction(value, "tail vector", conversions)
        for value in parent.vector_hex
    )
    total_variation = sum((abs(value) for value in vector), Fraction(0))
    remainder = total_variation * growth_tail
    rounding = []
    widths = []
    unique_count = 0
    for ordinal, value in enumerate(checkpoint.partial):
        lower, upper = _product_interval(
            exp_negative_lower,
            exp_negative_upper,
            value - remainder,
            value + remainder,
        )
        lower_hex = _round_fraction(lower)
        upper_hex = _round_fraction(upper)
        unique = lower_hex == upper_hex
        unique_count += int(unique)
        widths.append(upper - lower)
        rounding.append(
            {
                "ordinal": ordinal,
                "lower_hex": lower_hex,
                "upper_hex": upper_hex,
                "unique": unique,
            }
        )
    rounding_raw = json.dumps(
        rounding, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return {
        "included_index": TARGET_INDEX,
        "ratio_denominator": ratio_denominator,
        "argument": _fraction_pair(argument),
        "tail_argument": _fraction_pair(tail_argument),
        "total_variation": _fraction_pair(total_variation),
        "exponential_positive_lower": _fraction_pair(exp_positive_lower),
        "exponential_positive_upper": _fraction_pair(exp_positive_upper),
        "growth_tail": _fraction_pair(growth_tail),
        "remainder_bound": _fraction_pair(remainder),
        "maximum_interval_width": _fraction_pair(max(widths, default=Fraction(0))),
        "coordinate_count": len(rounding),
        "unique_coordinate_count": unique_count,
        "all_coordinates_unique": unique_count == len(rounding),
        "rounding": rounding,
        "rounding_sha256": _sha256(rounding_raw),
        "tail_vector_fp64_conversions": len(conversions),
        "rounding_calls": 2 * len(rounding),
    }


def encode_raw_index537(checkpoint):
    """Encode the exact uncompressed index537 state for compact containment."""

    if checkpoint.included_index != TARGET_INDEX:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index537")
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
    body_raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return json.dumps(
        {"body": body, "body_sha256": _sha256(body_raw)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
