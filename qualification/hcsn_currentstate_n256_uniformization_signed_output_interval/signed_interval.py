"""Certify unique binary64 rounding for signed substochastic uniformization.

This source uses exact rational arithmetic.  It propagates the signed partial
Poisson series directly and bounds the omitted signed remainder by propagating
the input total variation through a substochastic transition.  It remains a
small finite fixture proof: authentic N256 loading, augmented non-substochastic
channels, dynamic continuation, and provider qualification remain open.
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


class SignedUniformizationIntervalError(ValueError):
    """Raised when a requested proof is outside the signed narrow domain."""


@dataclass(frozen=True)
class RoundedSignedOutputInterval:
    lower_numerator: str
    lower_denominator: str
    upper_numerator: str
    upper_denominator: str
    output_hex: str


@dataclass(frozen=True)
class SignedUniformizationIntervalCertificate:
    highest_included_poisson_index: int
    conversion_certificates: tuple[Fp64ConversionCertificate, ...]
    total_variation_numerator: str
    total_variation_denominator: str
    max_output_interval_width_numerator: str
    max_output_interval_width_denominator: str
    outputs: tuple[RoundedSignedOutputInterval, ...]
    exact_signed_rational_interval_certified: bool = True
    binary64_unique_rounding_certified: bool = True
    substochastic_transition_certified: bool = True
    non_substochastic_certified: bool = False
    authentic_n256_bundle_loaded: bool = False
    n256_provider_qualified: bool = False


def _exact_fraction(input_hex, name, certificates):
    try:
        _, certificate = fp64_hex_to_exact_decimal(input_hex)
    except Fp64InputError as error:
        raise SignedUniformizationIntervalError(f"{name}: {error}") from error
    certificates.append(certificate)
    return Fraction(
        int(certificate.exact_numerator),
        1 << certificate.denominator_power_of_two,
    )


def _canonical_operator(rows_hex, certificates):
    if not isinstance(rows_hex, (tuple, list)) or not rows_hex:
        raise SignedUniformizationIntervalError(
            "operator rows must be a non-empty sequence"
        )
    dimension = len(rows_hex)
    rows = []
    diagonals = []
    for row_index, row in enumerate(rows_hex):
        if not isinstance(row, (tuple, list)):
            raise SignedUniformizationIntervalError(
                "each operator row must be a sequence"
            )
        prior = -1
        values = {}
        diagonal = Fraction(0)
        for entry in row:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise SignedUniformizationIntervalError(
                    "operator entry must be (column, value_hex)"
                )
            column, value_hex = entry
            if not isinstance(column, int) or isinstance(column, bool):
                raise SignedUniformizationIntervalError(
                    "operator column must be an integer"
                )
            if not 0 <= column < dimension or column <= prior:
                raise SignedUniformizationIntervalError(
                    "operator columns must be unique, sorted, and in range"
                )
            prior = column
            value = _exact_fraction(value_hex, "operator value", certificates)
            if column == row_index:
                if value > 0:
                    raise SignedUniformizationIntervalError(
                        "Metzler diagonal must be non-positive"
                    )
                diagonal = value
            elif value < 0:
                raise SignedUniformizationIntervalError(
                    "Metzler off-diagonal must be non-negative"
                )
            if value:
                values[column] = value
        if sum(values.values(), Fraction(0)) > 0:
            raise SignedUniformizationIntervalError(
                "generator row sum must be non-positive"
            )
        rows.append(values)
        diagonals.append(diagonal)
    return tuple(rows), tuple(diagonals)


def _transition_rows(operator, diagonals, rate):
    transition = []
    for index, row in enumerate(operator):
        values = {column: value / rate for column, value in row.items()}
        values[index] = values.get(index, Fraction(0)) + 1
        if any(value < 0 for value in values.values()):
            raise SignedUniformizationIntervalError(
                "uniformized transition has a negative entry"
            )
        if sum(values.values(), Fraction(0)) > 1:
            raise SignedUniformizationIntervalError(
                "uniformized transition must be substochastic"
            )
        transition.append(
            tuple((column, value) for column, value in sorted(values.items()) if value)
        )
    return tuple(transition)


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
        raise SignedUniformizationIntervalError(str(error)) from error
    return output_hex


def _product_interval(exp_lower, exp_upper, value_lower, value_upper):
    products = (
        exp_lower * value_lower,
        exp_lower * value_upper,
        exp_upper * value_lower,
        exp_upper * value_upper,
    )
    return min(products), max(products)


def signed_uniformization_outputs_from_fp64_intervals(
    rows_hex, vector_hex, duration_hex, *, max_terms=1024
):
    """Return uniquely rounded signed outputs and an exact interval certificate."""

    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise SignedUniformizationIntervalError("max_terms must be a positive integer")
    certificates = []
    operator, diagonals = _canonical_operator(rows_hex, certificates)
    if not isinstance(vector_hex, (tuple, list)) or len(vector_hex) != len(operator):
        raise SignedUniformizationIntervalError("vector dimension mismatch")
    vector = tuple(
        _exact_fraction(value, "vector value", certificates) for value in vector_hex
    )
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise SignedUniformizationIntervalError("duration must be non-negative")
    total_variation = sum((abs(value) for value in vector), Fraction(0))
    rate = max((-value for value in diagonals), default=Fraction(0))
    if duration == 0 or rate == 0:
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
        return tuple(output.output_hex for output in outputs), SignedUniformizationIntervalCertificate(
            highest_included_poisson_index=0,
            conversion_certificates=tuple(certificates),
            total_variation_numerator=str(total_variation.numerator),
            total_variation_denominator=str(total_variation.denominator),
            max_output_interval_width_numerator="0",
            max_output_interval_width_denominator="1",
            outputs=outputs,
        )

    transition = _transition_rows(operator, diagonals, rate)
    argument = rate * duration
    iterate = vector
    coefficient = Fraction(1)
    exponential_sum = Fraction(1)
    partial = list(vector)
    for term_index in range(max_terms):
        next_coefficient = coefficient * argument / (term_index + 1)
        ratio_denominator = term_index + 2
        if argument < ratio_denominator:
            tail = next_coefficient / (1 - argument / ratio_denominator)
            exp_positive_lower = exponential_sum
            exp_positive_upper = exponential_sum + tail
            exp_negative_lower = 1 / exp_positive_upper
            exp_negative_upper = 1 / exp_positive_lower
            remainder_bound = total_variation * tail
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
                max_width = max(widths, default=Fraction(0))
                certificate = SignedUniformizationIntervalCertificate(
                    highest_included_poisson_index=term_index,
                    conversion_certificates=tuple(certificates),
                    total_variation_numerator=str(total_variation.numerator),
                    total_variation_denominator=str(total_variation.denominator),
                    max_output_interval_width_numerator=str(max_width.numerator),
                    max_output_interval_width_denominator=str(max_width.denominator),
                    outputs=tuple(rounded_intervals),
                )
                return tuple(output.output_hex for output in certificate.outputs), certificate
        iterate = _row_action(iterate, transition)
        coefficient = next_coefficient
        exponential_sum += coefficient
        partial = [
            left + coefficient * right
            for left, right in zip(partial, iterate, strict=True)
        ]
    raise SignedUniformizationIntervalError(
        "max_terms reached before every output had unique binary64 rounding"
    )
