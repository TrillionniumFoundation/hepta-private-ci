"""Exact interval continuation across one fixed scheduled reset.

The first finite segment is produced by the separately frozen augmented
selector candidate.  Its exact rational output intervals are transformed by a
nonnegative reset map that moves accumulated lower-hit mass back to the active
coordinates.  A second finite segment then propagates the full rational
interval state without first collapsing it to binary64.

This proves only a fixed-time scheduled-reset composition on the small frozen
fixture.  It is not a hit-specific deterministic-delay law, an authentic N256
provider, or a second-cycle full-domain qualification.
"""

from dataclasses import dataclass
from fractions import Fraction

from qualification.hcsn_currentstate_augmented_selector_interval.augmented_selector import (
    AugmentedSelectorCertificate,
    augmented_selector_outputs_from_fp64_amplitude,
)
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


class ScheduledResetIntervalError(ValueError):
    """Raised when interval continuation leaves the frozen proof domain."""


@dataclass(frozen=True)
class ScheduledResetCertificate:
    first_segment: AugmentedSelectorCertificate
    second_segment: NonSubstochasticSignedIntervalCertificate
    reset_lower: tuple[str, ...]
    reset_upper: tuple[str, ...]
    reset_at_fixed_schedule_encoded: bool = True
    full_interval_state_propagated: bool = True
    hit_specific_deterministic_delay_encoded: bool = False
    authentic_n256_bundle_loaded: bool = False
    current_state_provider_qualified: bool = False


_ROWS = (
    (
        (0, "c008000000000000"),
        (1, "3ff0000000000000"),
        (2, "4000000000000000"),
        (3, "3ff0000000000000"),
    ),
    (),
    (),
    (),
    (
        (4, "c00c000000000000"),
        (5, "4000000000000000"),
        (6, "3ff0000000000000"),
    ),
    (),
    (),
)


def _fraction(numerator, denominator):
    return Fraction(int(numerator), int(denominator))


def _intervals(certificate):
    lower = tuple(
        _fraction(output.lower_numerator, output.lower_denominator)
        for output in certificate.outputs
    )
    upper = tuple(
        _fraction(output.upper_numerator, output.upper_denominator)
        for output in certificate.outputs
    )
    return lower, upper


def _scheduled_reset(lower, upper):
    if len(lower) != 7 or len(upper) != 7:
        raise ScheduledResetIntervalError("scheduled reset requires seven coordinates")
    if any(left > right for left, right in zip(lower, upper, strict=True)):
        raise ScheduledResetIntervalError("invalid input interval")
    reset_lower = (
        lower[0] + lower[2],
        lower[1],
        Fraction(0),
        lower[3],
        lower[4] + lower[5],
        Fraction(0),
        lower[6],
    )
    reset_upper = (
        upper[0] + upper[2],
        upper[1],
        Fraction(0),
        upper[3],
        upper[4] + upper[5],
        Fraction(0),
        upper[6],
    )
    return reset_lower, reset_upper


def _propagate_interval(rows_hex, lower, upper, duration_hex, *, max_terms=1024):
    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise ScheduledResetIntervalError("max_terms must be a positive integer")
    certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        rows_hex, certificates
    )
    if len(lower) != len(operator) or len(upper) != len(operator):
        raise ScheduledResetIntervalError("interval dimension mismatch")
    if any(left > right for left, right in zip(lower, upper, strict=True)):
        raise ScheduledResetIntervalError("invalid propagation interval")
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise ScheduledResetIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )
    argument = rate * duration
    tail_argument = argument * transition_l1_norm
    total_variation = sum(
        (max(abs(left), abs(right)) for left, right in zip(lower, upper, strict=True)),
        Fraction(0),
    )
    if duration == 0:
        rounded = []
        for left, right in zip(lower, upper, strict=True):
            left_hex = _round_fraction(left)
            right_hex = _round_fraction(right)
            if left_hex != right_hex:
                raise ScheduledResetIntervalError(
                    "zero-duration interval lacks unique binary64 rounding"
                )
            rounded.append(
                RoundedSignedOutputInterval(
                    str(left.numerator),
                    str(left.denominator),
                    str(right.numerator),
                    str(right.denominator),
                    left_hex,
                )
            )
        certificate = _certificate(
            0,
            certificates,
            rate,
            transition_l1_norm,
            tail_argument,
            total_variation,
            max((right - left for left, right in zip(lower, upper, strict=True))),
            tuple(rounded),
        )
        return tuple(item.output_hex for item in rounded), certificate

    iterate_lower = tuple(lower)
    iterate_upper = tuple(upper)
    coefficient = Fraction(1)
    growth_coefficient = Fraction(1)
    exponential_sum = Fraction(1)
    partial_lower = list(lower)
    partial_upper = list(upper)
    for included_index in range(max_terms):
        denominator = included_index + 1
        ratio_denominator = included_index + 2
        next_coefficient = coefficient * argument / denominator
        next_growth_coefficient = (
            growth_coefficient * tail_argument / denominator
        )
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
            rounded = []
            widths = []
            unique = True
            for left, right in zip(partial_lower, partial_upper, strict=True):
                output_lower, output_upper = _product_interval(
                    exp_negative_lower,
                    exp_negative_upper,
                    left - remainder_bound,
                    right + remainder_bound,
                )
                lower_hex = _round_fraction(output_lower)
                upper_hex = _round_fraction(output_upper)
                unique = unique and lower_hex == upper_hex
                widths.append(output_upper - output_lower)
                rounded.append(
                    RoundedSignedOutputInterval(
                        str(output_lower.numerator),
                        str(output_lower.denominator),
                        str(output_upper.numerator),
                        str(output_upper.denominator),
                        lower_hex,
                    )
                )
            if unique:
                certificate = _certificate(
                    included_index,
                    certificates,
                    rate,
                    transition_l1_norm,
                    tail_argument,
                    total_variation,
                    max(widths, default=Fraction(0)),
                    tuple(rounded),
                )
                return tuple(item.output_hex for item in rounded), certificate
        iterate_lower = _row_action(iterate_lower, transition)
        iterate_upper = _row_action(iterate_upper, transition)
        coefficient = next_coefficient
        growth_coefficient = next_growth_coefficient
        exponential_sum += coefficient
        partial_lower = [
            left + coefficient * right
            for left, right in zip(partial_lower, iterate_lower, strict=True)
        ]
        partial_upper = [
            left + coefficient * right
            for left, right in zip(partial_upper, iterate_upper, strict=True)
        ]
    raise NonSubstochasticSignedIntervalError(
        "max_terms reached before every reset output had unique binary64 rounding"
    )


def scheduled_reset_outputs_from_fp64_amplitude(amplitude_hex, segment_duration_hex):
    """Continue one full interval state across a fixed scheduled reset."""

    _, first = augmented_selector_outputs_from_fp64_amplitude(
        amplitude_hex, segment_duration_hex
    )
    lower, upper = _intervals(first.interval_certificate)
    reset_lower, reset_upper = _scheduled_reset(lower, upper)
    outputs, second = _propagate_interval(
        _ROWS, reset_lower, reset_upper, segment_duration_hex
    )
    return outputs, ScheduledResetCertificate(
        first_segment=first,
        second_segment=second,
        reset_lower=tuple(str(value) for value in reset_lower),
        reset_upper=tuple(str(value) for value in reset_upper),
    )
