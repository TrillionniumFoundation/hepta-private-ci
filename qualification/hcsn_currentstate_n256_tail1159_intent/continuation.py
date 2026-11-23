"""Exact index537-to-1159 continuation and final signed tail interval."""

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
    inspect_canonical_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.rounding import (
    round_fraction_without_decimal_certificate,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    _exact_fraction,
    _product_interval,
    _row_action,
)


SOURCE_INDEX = 537
TARGET_INDEX = 1159
SOURCE_SCHEMA = "hcsn-n256-authentic-index537-tail-checkpoint-v1"
TARGET_SCHEMA = "hcsn-n256-authentic-index1159-tail-checkpoint-v1"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_index537(raw, parent_payload):
    """Parse one archived canonical index537 full state."""

    metadata = inspect_canonical_checkpoint(raw, SOURCE_SCHEMA, SOURCE_INDEX)
    body = json.loads(raw)["body"]
    if body["parent_payload_sha256"] != _sha256(parent_payload):
        raise NonSubstochasticSignedIntervalError("index537 parent digest mismatch")
    return AuthenticCheckpoint(
        source_payload_sha256=body["source_payload_sha256"],
        parent_payload_sha256=body["parent_payload_sha256"],
        lane=metadata["lane"],
        included_index=SOURCE_INDEX,
        iterate=tuple(_fraction_from_pair(value, "iterate") for value in body["iterate"]),
        coefficient=_fraction_from_pair(body["coefficient"], "coefficient"),
        growth_coefficient=_fraction_from_pair(
            body["growth_coefficient"], "growth coefficient"
        ),
        exponential_sum=_fraction_from_pair(
            body["exponential_sum"], "exponential sum"
        ),
        partial=tuple(_fraction_from_pair(value, "partial") for value in body["partial"]),
    )


def parse_index1159(raw):
    """Parse one canonical index1159 state without replaying its parent."""

    metadata = inspect_canonical_checkpoint(raw, TARGET_SCHEMA, TARGET_INDEX)
    body = json.loads(raw)["body"]
    checkpoint = AuthenticCheckpoint(
        source_payload_sha256=body["source_payload_sha256"],
        parent_payload_sha256=body["parent_payload_sha256"],
        lane=metadata["lane"],
        included_index=TARGET_INDEX,
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
    if len(checkpoint.iterate) != metadata["vector_length"] or len(
        checkpoint.partial
    ) != metadata["vector_length"]:
        raise NonSubstochasticSignedIntervalError(
            "index1159 vector dimension mismatch"
        )
    return checkpoint


def advance_to_index1159(checkpoint, parent_payload, progress=None):
    """Apply exactly 622 authentic recurrence row actions."""

    if checkpoint.included_index != SOURCE_INDEX:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index537")
    parent = decode_authentic_firststep_cursor(parent_payload)
    if parent.lane != checkpoint.lane:
        raise NonSubstochasticSignedIntervalError("checkpoint lane differs")
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    current = checkpoint
    for next_index in range(SOURCE_INDEX + 1, TARGET_INDEX + 1):
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


def final_tail_check(checkpoint, parent_payload):
    """Evaluate one unchanged ratio-bound signed interval at index1159."""

    if checkpoint.included_index != TARGET_INDEX:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index1159")
    parent = decode_authentic_firststep_cursor(parent_payload)
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    denominator = TARGET_INDEX + 1
    ratio_denominator = TARGET_INDEX + 2
    if argument >= ratio_denominator or tail_argument >= ratio_denominator:
        raise NonSubstochasticSignedIntervalError("index1159 ratio bound is invalid")
    next_coefficient = checkpoint.coefficient * argument / denominator
    next_growth = checkpoint.growth_coefficient * tail_argument / denominator
    exponential_tail = next_coefficient / (1 - argument / ratio_denominator)
    positive_lower = checkpoint.exponential_sum
    positive_upper = checkpoint.exponential_sum + exponential_tail
    negative_lower = 1 / positive_upper
    negative_upper = 1 / positive_lower
    growth_tail = next_growth / (1 - tail_argument / ratio_denominator)
    conversions = []
    vector = tuple(
        _exact_fraction(value, "tail vector", conversions)
        for value in parent.vector_hex
    )
    remainder = sum((abs(value) for value in vector), Fraction(0)) * growth_tail
    rounding = []
    widths = []
    for ordinal, value in enumerate(checkpoint.partial):
        lower, upper = _product_interval(
            negative_lower, negative_upper, value - remainder, value + remainder
        )
        lower_hex = round_fraction_without_decimal_certificate(lower)
        upper_hex = round_fraction_without_decimal_certificate(upper)
        widths.append(upper - lower)
        rounding.append(
            {
                "ordinal": ordinal,
                "lower_hex": lower_hex,
                "upper_hex": upper_hex,
                "unique": lower_hex == upper_hex,
            }
        )
    unique = sum(record["unique"] for record in rounding)
    canonical = json.dumps(rounding, sort_keys=True, separators=(",", ":")).encode()
    return {
        "included_index": TARGET_INDEX,
        "ratio_denominator": ratio_denominator,
        "argument": _fraction_pair(argument),
        "tail_argument": _fraction_pair(tail_argument),
        "growth_tail": _fraction_pair(growth_tail),
        "remainder_bound": _fraction_pair(remainder),
        "maximum_interval_width": _fraction_pair(max(widths, default=Fraction(0))),
        "coordinate_count": len(rounding),
        "unique_coordinate_count": unique,
        "all_coordinates_unique": unique == len(rounding),
        "rounding": rounding,
        "rounding_sha256": _sha256(canonical),
        "tail_vector_fp64_conversions": len(conversions),
        "rounding_calls": 2 * len(rounding),
    }


def encode_raw_index1159(checkpoint):
    """Encode the complete exact state without applying any compact cap."""

    if checkpoint.included_index != TARGET_INDEX:
        raise NonSubstochasticSignedIntervalError("checkpoint is not index1159")
    body = {
        "coefficient": _fraction_pair(checkpoint.coefficient),
        "exponential_sum": _fraction_pair(checkpoint.exponential_sum),
        "growth_coefficient": _fraction_pair(checkpoint.growth_coefficient),
        "included_index": TARGET_INDEX,
        "iterate": [_fraction_pair(value) for value in checkpoint.iterate],
        "lane": checkpoint.lane,
        "parent_payload_sha256": checkpoint.parent_payload_sha256,
        "partial": [_fraction_pair(value) for value in checkpoint.partial],
        "schema": TARGET_SCHEMA,
        "source_payload_sha256": checkpoint.source_payload_sha256,
    }
    body_raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return json.dumps(
        {"body": body, "body_sha256": _sha256(body_raw)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
