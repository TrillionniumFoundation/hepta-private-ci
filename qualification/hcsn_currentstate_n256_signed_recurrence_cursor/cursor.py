"""Cold-serializable exact recurrence cursor for bounded signed fixtures.

The cursor snapshots and validates one small request, then exposes a bounded
number of exact Poisson-tail checks per advance.  Its canonical JSON envelope
contains every exact recurrence variable needed to continue in a fresh
process.  This stage never loads or executes the authentic N256 bundle.
"""

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    RoundedSignedOutputInterval,
    _canonical_operator,
    _certificate,
    _exact_fraction,
    _product_interval,
    _round_fraction,
    _row_action,
    _transition_rows,
)


SCHEMA = "hcsn-signed-recurrence-cursor-small-fixture-v1"
MAX_DIMENSION = 32
MAX_TERMS = 1024
MAX_CURSOR_BYTES = 131_072


@dataclass(frozen=True)
class SignedRecurrenceCursor:
    """Complete exact state for one bounded signed recurrence."""

    rows_hex: tuple[tuple[tuple[int, str], ...], ...]
    vector_hex: tuple[str, ...]
    duration_hex: str
    max_terms: int
    included_index: int
    iterate: tuple[Fraction, ...]
    coefficient: Fraction
    growth_coefficient: Fraction
    exponential_sum: Fraction
    partial: tuple[Fraction, ...]
    transition: tuple[tuple[tuple[int, Fraction], ...], ...]
    rate: Fraction
    transition_l1_norm: Fraction
    duration: Fraction
    total_variation: Fraction
    certificates: tuple


def _freeze_rows(rows_hex):
    if not isinstance(rows_hex, (tuple, list)):
        raise NonSubstochasticSignedIntervalError("operator rows must be a sequence")
    frozen = []
    for row in rows_hex:
        if not isinstance(row, (tuple, list)):
            raise NonSubstochasticSignedIntervalError("operator row must be a sequence")
        frozen.append(tuple(tuple(entry) for entry in row))
    return tuple(frozen)


def start_signed_recurrence_cursor(
    rows_hex, vector_hex, duration_hex, *, max_terms=MAX_TERMS
):
    """Snapshot and validate a bounded request before recurrence work."""

    if (
        not isinstance(max_terms, int)
        or isinstance(max_terms, bool)
        or not 1 <= max_terms <= MAX_TERMS
    ):
        raise NonSubstochasticSignedIntervalError("max_terms outside bounded domain")
    frozen_rows = _freeze_rows(rows_hex)
    if not frozen_rows or len(frozen_rows) > MAX_DIMENSION:
        raise NonSubstochasticSignedIntervalError("dimension outside bounded domain")
    if not isinstance(vector_hex, (tuple, list)):
        raise NonSubstochasticSignedIntervalError("vector must be a sequence")
    frozen_vector = tuple(vector_hex)

    certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        frozen_rows, certificates
    )
    if len(frozen_vector) != len(operator):
        raise NonSubstochasticSignedIntervalError("vector dimension mismatch")
    vector = tuple(
        _exact_fraction(value, "vector value", certificates)
        for value in frozen_vector
    )
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise NonSubstochasticSignedIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )
    return SignedRecurrenceCursor(
        rows_hex=frozen_rows,
        vector_hex=frozen_vector,
        duration_hex=duration_hex,
        max_terms=max_terms,
        included_index=0,
        iterate=vector,
        coefficient=Fraction(1),
        growth_coefficient=Fraction(1),
        exponential_sum=Fraction(1),
        partial=vector,
        transition=transition,
        rate=rate,
        transition_l1_norm=transition_l1_norm,
        duration=duration,
        total_variation=sum((abs(value) for value in vector), Fraction(0)),
        certificates=tuple(certificates),
    )


def _result_if_unique(cursor):
    tail_argument = cursor.rate * cursor.duration * cursor.transition_l1_norm
    if cursor.duration == 0:
        outputs = tuple(
            RoundedSignedOutputInterval(
                str(value.numerator),
                str(value.denominator),
                str(value.numerator),
                str(value.denominator),
                _round_fraction(value),
            )
            for value in cursor.partial
        )
        return tuple(item.output_hex for item in outputs), _certificate(
            0,
            cursor.certificates,
            cursor.rate,
            cursor.transition_l1_norm,
            tail_argument,
            cursor.total_variation,
            Fraction(0),
            outputs,
        )

    argument = cursor.rate * cursor.duration
    denominator = cursor.included_index + 1
    ratio_denominator = cursor.included_index + 2
    next_coefficient = cursor.coefficient * argument / denominator
    next_growth_coefficient = (
        cursor.growth_coefficient * tail_argument / denominator
    )
    if argument >= ratio_denominator or tail_argument >= ratio_denominator:
        return None
    exponential_tail = next_coefficient / (1 - argument / ratio_denominator)
    exp_positive_lower = cursor.exponential_sum
    exp_positive_upper = cursor.exponential_sum + exponential_tail
    exp_negative_lower = 1 / exp_positive_upper
    exp_negative_upper = 1 / exp_positive_lower
    growth_tail = next_growth_coefficient / (
        1 - tail_argument / ratio_denominator
    )
    remainder_bound = cursor.total_variation * growth_tail
    rounded_intervals = []
    widths = []
    for value in cursor.partial:
        lower, upper = _product_interval(
            exp_negative_lower,
            exp_negative_upper,
            value - remainder_bound,
            value + remainder_bound,
        )
        lower_hex = _round_fraction(lower)
        if lower_hex != _round_fraction(upper):
            return None
        widths.append(upper - lower)
        rounded_intervals.append(
            RoundedSignedOutputInterval(
                str(lower.numerator),
                str(lower.denominator),
                str(upper.numerator),
                str(upper.denominator),
                lower_hex,
            )
        )
    outputs = tuple(rounded_intervals)
    return tuple(item.output_hex for item in outputs), _certificate(
        cursor.included_index,
        cursor.certificates,
        cursor.rate,
        cursor.transition_l1_norm,
        tail_argument,
        cursor.total_variation,
        max(widths, default=Fraction(0)),
        outputs,
    )


def advance_signed_recurrence_cursor(cursor, *, tail_checks):
    """Perform at most ``tail_checks`` exact checks and return state or result."""

    if (
        not isinstance(tail_checks, int)
        or isinstance(tail_checks, bool)
        or tail_checks < 1
    ):
        raise NonSubstochasticSignedIntervalError(
            "tail_checks must be a positive integer"
        )
    current = cursor
    for _ in range(tail_checks):
        if current.included_index >= current.max_terms:
            raise NonSubstochasticSignedIntervalError(
                "max_terms reached before every output had unique binary64 rounding"
            )
        result = _result_if_unique(current)
        if result is not None:
            return None, result
        argument = current.rate * current.duration
        tail_argument = argument * current.transition_l1_norm
        denominator = current.included_index + 1
        next_coefficient = current.coefficient * argument / denominator
        next_growth_coefficient = (
            current.growth_coefficient * tail_argument / denominator
        )
        next_iterate = _row_action(current.iterate, current.transition)
        current = replace(
            current,
            included_index=current.included_index + 1,
            iterate=next_iterate,
            coefficient=next_coefficient,
            growth_coefficient=next_growth_coefficient,
            exponential_sum=current.exponential_sum + next_coefficient,
            partial=tuple(
                left + next_coefficient * right
                for left, right in zip(
                    current.partial, next_iterate, strict=True
                )
            ),
        )
        if current.included_index >= current.max_terms:
            raise NonSubstochasticSignedIntervalError(
                "max_terms reached before every output had unique binary64 rounding"
            )
    return current, None


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
        raise NonSubstochasticSignedIntervalError(
            f"invalid {name} fraction"
        ) from error
    if _fraction_pair(value) != pair:
        raise NonSubstochasticSignedIntervalError(f"noncanonical {name} fraction")
    return value


def encode_signed_recurrence_cursor(cursor):
    """Encode a canonical, hash-bound cursor envelope."""

    body = {
        "coefficient": _fraction_pair(cursor.coefficient),
        "duration_hex": cursor.duration_hex,
        "exponential_sum": _fraction_pair(cursor.exponential_sum),
        "growth_coefficient": _fraction_pair(cursor.growth_coefficient),
        "included_index": cursor.included_index,
        "iterate": [_fraction_pair(value) for value in cursor.iterate],
        "max_terms": cursor.max_terms,
        "partial": [_fraction_pair(value) for value in cursor.partial],
        "rows_hex": [
            [[column, value] for column, value in row]
            for row in cursor.rows_hex
        ],
        "schema": SCHEMA,
        "vector_hex": list(cursor.vector_hex),
    }
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    envelope = {
        "body": body,
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    }
    payload = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("cursor exceeds byte cap")
    return payload


def decode_signed_recurrence_cursor(payload):
    """Decode a canonical cursor and revalidate its frozen request."""

    if not isinstance(payload, bytes) or len(payload) > MAX_CURSOR_BYTES:
        raise NonSubstochasticSignedIntervalError("invalid cursor payload")
    try:
        envelope = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NonSubstochasticSignedIntervalError("invalid cursor JSON") from error
    if not isinstance(envelope, dict) or set(envelope) != {"body", "body_sha256"}:
        raise NonSubstochasticSignedIntervalError("invalid cursor envelope")
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if canonical != payload:
        raise NonSubstochasticSignedIntervalError("noncanonical cursor JSON")
    body = envelope["body"]
    expected_keys = {
        "coefficient",
        "duration_hex",
        "exponential_sum",
        "growth_coefficient",
        "included_index",
        "iterate",
        "max_terms",
        "partial",
        "rows_hex",
        "schema",
        "vector_hex",
    }
    if not isinstance(body, dict) or set(body) != expected_keys:
        raise NonSubstochasticSignedIntervalError("invalid cursor body")
    body_bytes = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        not isinstance(envelope["body_sha256"], str)
        or hashlib.sha256(body_bytes).hexdigest() != envelope["body_sha256"]
        or body["schema"] != SCHEMA
    ):
        raise NonSubstochasticSignedIntervalError("cursor digest or schema mismatch")
    cursor = start_signed_recurrence_cursor(
        body["rows_hex"],
        body["vector_hex"],
        body["duration_hex"],
        max_terms=body["max_terms"],
    )
    included_index = body["included_index"]
    if (
        not isinstance(included_index, int)
        or isinstance(included_index, bool)
        or not 0 <= included_index < cursor.max_terms
    ):
        raise NonSubstochasticSignedIntervalError("invalid included index")
    iterate = tuple(
        _fraction_from_pair(value, "iterate") for value in body["iterate"]
    )
    partial = tuple(
        _fraction_from_pair(value, "partial") for value in body["partial"]
    )
    if len(iterate) != len(cursor.iterate) or len(partial) != len(cursor.partial):
        raise NonSubstochasticSignedIntervalError("cursor dimension mismatch")
    return replace(
        cursor,
        included_index=included_index,
        iterate=iterate,
        coefficient=_fraction_from_pair(body["coefficient"], "coefficient"),
        growth_coefficient=_fraction_from_pair(
            body["growth_coefficient"], "growth coefficient"
        ),
        exponential_sum=_fraction_from_pair(
            body["exponential_sum"], "exponential sum"
        ),
        partial=partial,
    )
