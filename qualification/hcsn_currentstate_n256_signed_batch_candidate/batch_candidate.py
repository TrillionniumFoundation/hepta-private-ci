"""Shared-parse batch candidate for the exact signed interval provider.

This candidate parses one operator and one duration once, then evaluates a
bounded sequence of vectors with the unchanged exact-rational recurrence.  It
is intentionally limited to small synthetic fixtures in this stage.  It does
not load or execute the authentic N256 bundle.
"""

from dataclasses import dataclass
from fractions import Fraction

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalCertificate,
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


MAX_BATCH_VECTORS = 16


@dataclass(frozen=True)
class SharedParseBatchResult:
    """Per-vector scalar-compatible results and explicit shared-work counts."""

    outputs: tuple[tuple[str, ...], ...]
    certificates: tuple[NonSubstochasticSignedIntervalCertificate, ...]
    vector_count: int
    operator_parse_count: int = 1
    duration_parse_count: int = 1
    authentic_n256_bundle_loaded: bool = False
    n256_qualified: bool = False


def _outputs_from_parsed(
    vector,
    duration,
    transition,
    rate,
    transition_l1_norm,
    certificates,
    max_terms,
):
    argument = rate * duration
    tail_argument = argument * transition_l1_norm
    total_variation = sum((abs(value) for value in vector), Fraction(0))

    if duration == 0:
        outputs = tuple(
            RoundedSignedOutputInterval(
                str(value.numerator),
                str(value.denominator),
                str(value.numerator),
                str(value.denominator),
                _round_fraction(value),
            )
            for value in vector
        )
        return tuple(output.output_hex for output in outputs), _certificate(
            0,
            certificates,
            rate,
            transition_l1_norm,
            tail_argument,
            total_variation,
            Fraction(0),
            outputs,
        )

    iterate = vector
    coefficient = Fraction(1)
    growth_coefficient = Fraction(1)
    exponential_sum = Fraction(1)
    partial = list(vector)
    for included_index in range(max_terms):
        denominator = included_index + 1
        ratio_denominator = included_index + 2
        next_coefficient = coefficient * argument / denominator
        next_growth_coefficient = growth_coefficient * tail_argument / denominator
        if argument < ratio_denominator and tail_argument < ratio_denominator:
            exponential_tail = next_coefficient / (
                1 - argument / ratio_denominator
            )
            exp_positive_lower = exponential_sum
            exp_positive_upper = exponential_sum + exponential_tail
            exp_negative_lower = 1 / exp_positive_upper
            exp_negative_upper = 1 / exp_positive_lower
            growth_tail = next_growth_coefficient / (
                1 - tail_argument / ratio_denominator
            )
            remainder_bound = total_variation * growth_tail
            rounded_intervals = []
            widths = []
            unique = True
            for value in partial:
                lower, upper = _product_interval(
                    exp_negative_lower,
                    exp_negative_upper,
                    value - remainder_bound,
                    value + remainder_bound,
                )
                lower_hex = _round_fraction(lower)
                upper_hex = _round_fraction(upper)
                unique = unique and lower_hex == upper_hex
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
            if unique:
                outputs = tuple(rounded_intervals)
                return tuple(
                    output.output_hex for output in outputs
                ), _certificate(
                    included_index,
                    certificates,
                    rate,
                    transition_l1_norm,
                    tail_argument,
                    total_variation,
                    max(widths, default=Fraction(0)),
                    outputs,
                )
        iterate = _row_action(iterate, transition)
        coefficient = next_coefficient
        growth_coefficient = next_growth_coefficient
        exponential_sum += coefficient
        partial = [
            left + coefficient * right
            for left, right in zip(partial, iterate, strict=True)
        ]
    raise NonSubstochasticSignedIntervalError(
        "max_terms reached before every output had unique binary64 rounding"
    )


def non_substochastic_signed_batch_outputs_from_fp64_intervals(
    rows_hex, vectors_hex, duration_hex, *, max_terms=1024
):
    """Return scalar-compatible results while parsing shared inputs once."""

    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise NonSubstochasticSignedIntervalError(
            "max_terms must be a positive integer"
        )
    if not isinstance(vectors_hex, (tuple, list)) or not vectors_hex:
        raise NonSubstochasticSignedIntervalError(
            "vectors must be a non-empty sequence"
        )
    if len(vectors_hex) > MAX_BATCH_VECTORS:
        raise NonSubstochasticSignedIntervalError(
            f"vectors exceed bounded batch limit {MAX_BATCH_VECTORS}"
        )

    operator_certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        rows_hex, operator_certificates
    )
    duration_certificates = []
    duration = _exact_fraction(duration_hex, "duration", duration_certificates)
    if duration < 0:
        raise NonSubstochasticSignedIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )

    parsed_vectors = []
    for vector_hex in vectors_hex:
        if not isinstance(vector_hex, (tuple, list)) or len(vector_hex) != len(
            operator
        ):
            raise NonSubstochasticSignedIntervalError("vector dimension mismatch")
        vector_certificates = []
        vector = tuple(
            _exact_fraction(value, "vector value", vector_certificates)
            for value in vector_hex
        )
        parsed_vectors.append((vector, vector_certificates))

    batch_outputs = []
    batch_certificates = []
    for vector, vector_certificates in parsed_vectors:
        certificates = [
            *operator_certificates,
            *vector_certificates,
            *duration_certificates,
        ]
        outputs, certificate = _outputs_from_parsed(
            vector,
            duration,
            transition,
            rate,
            transition_l1_norm,
            certificates,
            max_terms,
        )
        batch_outputs.append(outputs)
        batch_certificates.append(certificate)

    return SharedParseBatchResult(
        outputs=tuple(batch_outputs),
        certificates=tuple(batch_certificates),
        vector_count=len(vectors_hex),
    )
