"""Certify unique binary64 rounding of bounded positive uniformization outputs.

The implementation uses exact rational arithmetic.  It encloses exp(-a)
by reciprocating a positive Taylor enclosure for exp(a) and bounds the
remaining uniformization series with a geometric majorant.  The deliberately
narrow domain is a nonnegative vector and a finite substochastic transition
obtained from a Metzler generator.  Signed vectors, non-substochastic selector
augmentation, authentic N256 loading, and provider qualification remain open.
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


class UniformizationOutputIntervalError(ValueError):
    """Raised when the requested interval proof is outside the narrow domain."""


@dataclass(frozen=True)
class RoundedOutputInterval:
    lower_numerator: str
    lower_denominator: str
    upper_numerator: str
    upper_denominator: str
    output_hex: str


@dataclass(frozen=True)
class UniformizationOutputIntervalCertificate:
    highest_included_poisson_index: int
    conversion_certificates: tuple[Fp64ConversionCertificate, ...]
    exp_negative_lower_numerator: str
    exp_negative_lower_denominator: str
    exp_negative_upper_numerator: str
    exp_negative_upper_denominator: str
    poisson_tail_upper_numerator: str
    poisson_tail_upper_denominator: str
    max_output_interval_width_numerator: str
    max_output_interval_width_denominator: str
    outputs: tuple[RoundedOutputInterval, ...]
    exact_positive_rational_interval_certified: bool = True
    binary64_unique_rounding_certified: bool = True
    signed_vector_certified: bool = False
    non_substochastic_certified: bool = False
    authentic_n256_bundle_loaded: bool = False
    n256_provider_qualified: bool = False


def _exact_fraction(input_hex, name, certificates):
    try:
        _, certificate = fp64_hex_to_exact_decimal(input_hex)
    except Fp64InputError as error:
        raise UniformizationOutputIntervalError(f"{name}: {error}") from error
    certificates.append(certificate)
    return Fraction(
        int(certificate.exact_numerator),
        1 << certificate.denominator_power_of_two,
    )


def _canonical_operator(rows_hex, certificates):
    if not isinstance(rows_hex, (tuple, list)) or not rows_hex:
        raise UniformizationOutputIntervalError("operator rows must be a non-empty sequence")
    dimension = len(rows_hex)
    rows = []
    diagonals = []
    for row_index, row in enumerate(rows_hex):
        if not isinstance(row, (tuple, list)):
            raise UniformizationOutputIntervalError("each operator row must be a sequence")
        prior = -1
        values = {}
        diagonal = Fraction(0)
        for entry in row:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise UniformizationOutputIntervalError(
                    "operator entry must be (column, value_hex)"
                )
            column, value_hex = entry
            if not isinstance(column, int) or isinstance(column, bool):
                raise UniformizationOutputIntervalError("operator column must be an integer")
            if not 0 <= column < dimension or column <= prior:
                raise UniformizationOutputIntervalError(
                    "operator columns must be unique, sorted, and in range"
                )
            prior = column
            value = _exact_fraction(value_hex, "operator value", certificates)
            if column == row_index:
                if value > 0:
                    raise UniformizationOutputIntervalError(
                        "Metzler diagonal must be non-positive"
                    )
                diagonal = value
            elif value < 0:
                raise UniformizationOutputIntervalError(
                    "Metzler off-diagonal must be non-negative"
                )
            if value:
                values[column] = value
        if sum(values.values(), Fraction(0)) > 0:
            raise UniformizationOutputIntervalError(
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
            raise UniformizationOutputIntervalError(
                "uniformized transition has a negative entry"
            )
        if sum(values.values(), Fraction(0)) > 1:
            raise UniformizationOutputIntervalError(
                "uniformized transition must be substochastic"
            )
        transition.append(
            tuple((column, value) for column, value in sorted(values.items()) if value)
        )
    return tuple(transition)


def _row_action(vector, rows):
    output = [Fraction(0)] * len(vector)
    for row_index, source in enumerate(vector):
        if not source:
            continue
        for column, value in rows[row_index]:
            output[column] += source * value
    return tuple(output)


def _round_fraction(value):
    try:
        output_hex, _ = exact_rational_to_fp64_hex(value.numerator, value.denominator)
    except Fp64RoundingError as error:
        raise UniformizationOutputIntervalError(str(error)) from error
    return output_hex


def _exact_outputs(vector, certificates):
    outputs = []
    for value in vector:
        output_hex = _round_fraction(value)
        outputs.append(
            RoundedOutputInterval(
                str(value.numerator),
                str(value.denominator),
                str(value.numerator),
                str(value.denominator),
                output_hex,
            )
        )
    return UniformizationOutputIntervalCertificate(
        highest_included_poisson_index=0,
        conversion_certificates=tuple(certificates),
        exp_negative_lower_numerator="1",
        exp_negative_lower_denominator="1",
        exp_negative_upper_numerator="1",
        exp_negative_upper_denominator="1",
        poisson_tail_upper_numerator="0",
        poisson_tail_upper_denominator="1",
        max_output_interval_width_numerator="0",
        max_output_interval_width_denominator="1",
        outputs=tuple(outputs),
    )


def uniformization_outputs_from_fp64_intervals(
    rows_hex,
    vector_hex,
    duration_hex,
    *,
    max_terms=512,
):
    """Return uniquely rounded outputs and an exact positive interval certificate."""

    if not isinstance(max_terms, int) or isinstance(max_terms, bool) or max_terms < 1:
        raise UniformizationOutputIntervalError("max_terms must be a positive integer")
    certificates = []
    operator, diagonals = _canonical_operator(rows_hex, certificates)
    if not isinstance(vector_hex, (tuple, list)) or len(vector_hex) != len(operator):
        raise UniformizationOutputIntervalError("vector dimension mismatch")
    vector = tuple(
        _exact_fraction(value, "vector value", certificates) for value in vector_hex
    )
    if any(value < 0 for value in vector):
        raise UniformizationOutputIntervalError(
            "signed vectors remain outside the positive interval contract"
        )
    duration = _exact_fraction(duration_hex, "duration", certificates)
    if duration < 0:
        raise UniformizationOutputIntervalError("duration must be non-negative")
    if duration == 0:
        certificate = _exact_outputs(vector, certificates)
        return tuple(output.output_hex for output in certificate.outputs), certificate

    rate = max((-value for value in diagonals), default=Fraction(0))
    if rate == 0:
        certificate = _exact_outputs(vector, certificates)
        return tuple(output.output_hex for output in certificate.outputs), certificate
    transition = _transition_rows(operator, diagonals, rate)
    argument = rate * duration
    input_l1 = sum(vector, Fraction(0))
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
            rounded_intervals = []
            widths = []
            unique = True
            for value in partial:
                lower = exp_negative_lower * value
                upper = exp_negative_upper * (value + input_l1 * tail)
                lower_hex = _round_fraction(lower)
                upper_hex = _round_fraction(upper)
                unique = unique and lower_hex == upper_hex
                widths.append(upper - lower)
                rounded_intervals.append(
                    RoundedOutputInterval(
                        str(lower.numerator),
                        str(lower.denominator),
                        str(upper.numerator),
                        str(upper.denominator),
                        lower_hex,
                    )
                )
            if unique:
                max_width = max(widths, default=Fraction(0))
                certificate = UniformizationOutputIntervalCertificate(
                    highest_included_poisson_index=term_index,
                    conversion_certificates=tuple(certificates),
                    exp_negative_lower_numerator=str(exp_negative_lower.numerator),
                    exp_negative_lower_denominator=str(exp_negative_lower.denominator),
                    exp_negative_upper_numerator=str(exp_negative_upper.numerator),
                    exp_negative_upper_denominator=str(exp_negative_upper.denominator),
                    poisson_tail_upper_numerator=str(tail.numerator),
                    poisson_tail_upper_denominator=str(tail.denominator),
                    max_output_interval_width_numerator=str(max_width.numerator),
                    max_output_interval_width_denominator=str(max_width.denominator),
                    outputs=tuple(rounded_intervals),
                )
                return (
                    tuple(output.output_hex for output in certificate.outputs),
                    certificate,
                )

        iterate = _row_action(iterate, transition)
        coefficient = next_coefficient
        exponential_sum += coefficient
        partial = [
            left + coefficient * right
            for left, right in zip(partial, iterate, strict=True)
        ]
    raise UniformizationOutputIntervalError(
        "max_terms reached before every output had unique binary64 rounding"
    )

