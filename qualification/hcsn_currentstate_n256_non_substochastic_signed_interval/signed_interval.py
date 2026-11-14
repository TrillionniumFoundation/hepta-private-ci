"""Exact signed output intervals for a finite non-substochastic Metzler fixture.

The uniformized transition is nonnegative but may have row sum above one.  A
row-vector total-variation bound therefore grows by the exact maximum row sum
at each power.  The omitted Poisson series is bounded with that growth included
before the independently enclosed positive exponential is applied.

This is deliberately a small finite arithmetic candidate.  It does not load
the authentic N256 bundle or provide a current-state packet, serializer, model,
Torch, optimizer, training, migration, or production qualification.
"""

from dataclasses import dataclass
from fractions import Fraction

from qualification.hcsn_currentstate_n256_fp64_input_conversion.fp64_exact import (
    Fp64ConversionCertificate,
    Fp64InputError,
    fp64_hex_to_exact_decimal,
)
from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    Fp64RoundingError,
    exact_rational_to_fp64_hex,
)


class NonSubstochasticSignedIntervalError(ValueError):
    """Raised when a request is outside this narrow exact proof domain."""


@dataclass(frozen=True)
class RoundedSignedOutputInterval:
    lower_numerator: str
    lower_denominator: str
    upper_numerator: str
    upper_denominator: str
    output_hex: str


@dataclass(frozen=True)
class NonSubstochasticSignedIntervalCertificate:
    highest_included_poisson_index: int
    conversion_certificates: tuple[Fp64ConversionCertificate, ...]
    rate_numerator: str
    rate_denominator: str
    transition_l1_norm_numerator: str
    transition_l1_norm_denominator: str
    tail_argument_numerator: str
    tail_argument_denominator: str
    total_variation_numerator: str
    total_variation_denominator: str
    max_output_interval_width_numerator: str
    max_output_interval_width_denominator: str
    outputs: tuple[RoundedSignedOutputInterval, ...]
    exact_signed_rational_interval_certified: bool = True
    binary64_unique_rounding_certified: bool = True
    nonnegative_transition_certified: bool = True
    non_substochastic_transition_certified: bool = True
    authentic_n256_bundle_loaded: bool = False
    current_state_provider_qualified: bool = False


def _exact_fraction(input_hex, name, certificates):
    try:
        _, certificate = fp64_hex_to_exact_decimal(input_hex)
    except Fp64InputError as error:
        raise NonSubstochasticSignedIntervalError(f"{name}: {error}") from error
    certificates.append(certificate)
    return Fraction(
        int(certificate.exact_numerator),
        1 << certificate.denominator_power_of_two,
    )


def _canonical_operator(rows_hex, certificates):
    if not isinstance(rows_hex, (tuple, list)) or not rows_hex:
        raise NonSubstochasticSignedIntervalError(
            "operator rows must be a non-empty sequence"
        )
    dimension = len(rows_hex)
    rows = []
    diagonals = []
    off_diagonal_sums = []
    for row_index, row in enumerate(rows_hex):
        if not isinstance(row, (tuple, list)):
            raise NonSubstochasticSignedIntervalError(
                "each operator row must be a sequence"
            )
        prior = -1
        values = {}
        diagonal = Fraction(0)
        off_diagonal_sum = Fraction(0)
        for entry in row:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise NonSubstochasticSignedIntervalError(
                    "operator entry must be (column, value_hex)"
                )
            column, value_hex = entry
            if not isinstance(column, int) or isinstance(column, bool):
                raise NonSubstochasticSignedIntervalError(
                    "operator column must be an integer"
                )
            if not 0 <= column < dimension or column <= prior:
                raise NonSubstochasticSignedIntervalError(
                    "operator columns must be unique, sorted, and in range"
                )
            prior = column
            value = _exact_fraction(value_hex, "operator value", certificates)
            if column == row_index:
                if value > 0:
                    raise NonSubstochasticSignedIntervalError(
                        "Metzler diagonal must be non-positive"
                    )
                diagonal = value
            else:
                if value < 0:
                    raise NonSubstochasticSignedIntervalError(
                        "Metzler off-diagonal must be non-negative"
                    )
                off_diagonal_sum += value
            if value:
                values[column] = value
        rows.append(values)
        diagonals.append(diagonal)
        off_diagonal_sums.append(off_diagonal_sum)
    return tuple(rows), tuple(diagonals), tuple(off_diagonal_sums)


def _transition_rows(operator, diagonals, off_diagonal_sums):
    rate = max(
        tuple(-value for value in diagonals) + tuple(off_diagonal_sums),
        default=Fraction(0),
    )
    if rate <= 0:
        raise NonSubstochasticSignedIntervalError(
            "non-substochastic proof requires a positive uniformization rate"
        )
    transition = []
    row_sums = []
    for index, row in enumerate(operator):
        values = {column: value / rate for column, value in row.items()}
        values[index] = values.get(index, Fraction(0)) + 1
        if any(value < 0 for value in values.values()):
            raise NonSubstochasticSignedIntervalError(
                "uniformized transition has a negative entry"
            )
        row_sum = sum(values.values(), Fraction(0))
        row_sums.append(row_sum)
        transition.append(
            tuple((column, value) for column, value in sorted(values.items()) if value)
        )
    transition_l1_norm = max(row_sums, default=Fraction(0))
    if transition_l1_norm <= 1:
        raise NonSubstochasticSignedIntervalError(
            "uniformized transition must be non-substochastic"
        )
    return tuple(transition), rate, transition_l1_norm


def _row_action(vector, rows):
    output = [Fraction(0)] * len(vector)
    for row_index, source in enumerate(vector):
        for column, value in rows[row_index]:
            output[column] += source * value
    return tuple(output)


def _round_fraction(value):
    try:
        output_hex, _ = exact_rational_to_fp64_hex(value.numerator, value.denominator)
    except Fp64RoundingError as error:
        raise NonSubstochasticSignedIntervalError(str(error)) from error
    return output_hex


def _product_interval(exp_lower, exp_upper, value_lower, value_upper):
    products = (
        exp_lower * value_lower,
        exp_lower * value_upper,
        exp_upper * value_lower,
        exp_upper * value_upper,
    )
    return min(products), max(products)


def non_substochastic_signed_outputs_from_fp64_intervals(
    rows_hex, vector_hex, duration_hex, *, max_terms=1024
):
    """Return uniquely rounded outputs with an exact growing-tail certificate."""

    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise NonSubstochasticSignedIntervalError(
            "max_terms must be a positive integer"
        )
    certificates = []
    operator, diagonals, off_diagonal_sums = _canonical_operator(
        rows_hex, certificates
    )
    if not isinstance(vector_hex, (tuple, list)) or len(vector_hex) != len(operator):
        raise NonSubstochasticSignedIntervalError("vector dimension mismatch")
    vector = tuple(
        _exact_fraction(value, "vector value", certificates) for value in vector_hex
    )
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise NonSubstochasticSignedIntervalError("duration must be non-negative")
    transition, rate, transition_l1_norm = _transition_rows(
        operator, diagonals, off_diagonal_sums
    )
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
                max_width = max(widths, default=Fraction(0))
                return tuple(output.output_hex for output in outputs), _certificate(
                    included_index,
                    certificates,
                    rate,
                    transition_l1_norm,
                    tail_argument,
                    total_variation,
                    max_width,
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


def _certificate(
    included_index,
    certificates,
    rate,
    transition_l1_norm,
    tail_argument,
    total_variation,
    max_width,
    outputs,
):
    return NonSubstochasticSignedIntervalCertificate(
        highest_included_poisson_index=included_index,
        conversion_certificates=tuple(certificates),
        rate_numerator=str(rate.numerator),
        rate_denominator=str(rate.denominator),
        transition_l1_norm_numerator=str(transition_l1_norm.numerator),
        transition_l1_norm_denominator=str(transition_l1_norm.denominator),
        tail_argument_numerator=str(tail_argument.numerator),
        tail_argument_denominator=str(tail_argument.denominator),
        total_variation_numerator=str(total_variation.numerator),
        total_variation_denominator=str(total_variation.denominator),
        max_output_interval_width_numerator=str(max_width.numerator),
        max_output_interval_width_denominator=str(max_width.denominator),
        outputs=tuple(outputs),
    )
