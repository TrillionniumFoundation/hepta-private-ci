"""Decimal row-vector action for finite Metzler operators.

This is an independently implemented uniformization primitive.  It neither
loads HCSN inputs nor implements the delayed packet engine.  The returned
bound covers Poisson-series truncation in the induced row-vector L1 norm;
input conversion and finite-precision rounding remain separate certificates.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext


class UniformizationError(ValueError):
    """Raised when the primitive cannot establish its declared domain."""


@dataclass(frozen=True)
class TruncationCertificate:
    terms: int
    decimal_precision: int
    uniformization_rate: str
    poisson_argument: str
    transition_l1_norm: str
    truncation_l1_upper_bound: str
    input_rounding_certified: bool = False
    finite_precision_rounding_certified: bool = False
    n256_provider_qualified: bool = False


def _decimal(value, name):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise UniformizationError(f"{name} must be a finite decimal") from error
    if not result.is_finite():
        raise UniformizationError(f"{name} must be a finite decimal")
    return result


def _validate_rows(rows):
    if not isinstance(rows, (tuple, list)) or not rows:
        raise UniformizationError("operator rows must be a non-empty sequence")
    dimension = len(rows)
    canonical = []
    diagonals = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, (tuple, list)):
            raise UniformizationError("each operator row must be a sequence")
        prior = -1
        entries = []
        diagonal = Decimal(0)
        for entry in row:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise UniformizationError("operator entry must be (column, value)")
            column, raw = entry
            if not isinstance(column, int) or not 0 <= column < dimension:
                raise UniformizationError("operator column is out of range")
            if column <= prior:
                raise UniformizationError("operator columns must be unique and sorted")
            prior = column
            value = _decimal(raw, "operator value")
            if column == row_index:
                if value > 0:
                    raise UniformizationError("Metzler diagonal must be non-positive")
                diagonal = value
            elif value < 0:
                raise UniformizationError("Metzler off-diagonal must be non-negative")
            if value:
                entries.append((column, value))
        canonical.append(tuple(entries))
        diagonals.append(diagonal)
    return tuple(canonical), tuple(diagonals)


def _transition_rows(rows, diagonals, rate):
    result = []
    for index, row in enumerate(rows):
        values = {column: value / rate for column, value in row}
        values[index] = values.get(index, Decimal(0)) + Decimal(1)
        if any(value < 0 for value in values.values()):
            raise UniformizationError("uniformized transition has a negative entry")
        result.append(tuple((column, value) for column, value in sorted(values.items()) if value))
    return tuple(result)


def _row_action(vector, rows):
    output = [Decimal(0)] * len(vector)
    for row_index, source in enumerate(vector):
        if not source:
            continue
        for column, value in rows[row_index]:
            output[column] += source * value
    return tuple(output)


def _tail_upper(input_l1, poisson_argument, transition_norm, terms, precision):
    """Geometric upper bound for the omitted positive exponential series."""

    with localcontext() as context:
        context.prec = precision + 16
        context.rounding = ROUND_CEILING
        z = poisson_argument * transition_norm
        next_index = terms + 1
        if Decimal(next_index + 1) <= z:
            return Decimal("Infinity")
        term = Decimal(1)
        for index in range(1, next_index + 1):
            term = term * z / Decimal(index)
        ratio = z / Decimal(next_index + 1)
        series_tail = term / (Decimal(1) - ratio)
        return input_l1 * (-poisson_argument).exp() * series_tail


def uniformization_action(rows, vector, duration, absolute_l1_tolerance, *, precision=80, max_terms=200000):
    """Return ``vector @ exp(rows * duration)`` and a truncation certificate.

    ``rows`` is a sorted sparse row representation of a finite Metzler matrix.
    Values and the initial row vector are accepted as decimal strings so binary
    float conversion is never implicit.
    """

    if not isinstance(precision, int) or precision < 32:
        raise UniformizationError("precision must be an integer at least 32")
    if not isinstance(max_terms, int) or max_terms < 1:
        raise UniformizationError("max_terms must be a positive integer")
    operator, diagonals = _validate_rows(rows)
    if not isinstance(vector, (tuple, list)) or len(vector) != len(operator):
        raise UniformizationError("vector dimension mismatch")
    initial = tuple(_decimal(value, "vector value") for value in vector)
    time = _decimal(duration, "duration")
    tolerance = _decimal(absolute_l1_tolerance, "absolute_l1_tolerance")
    if time < 0 or tolerance <= 0:
        raise UniformizationError("duration must be non-negative and tolerance positive")
    if time == 0:
        certificate = TruncationCertificate(0, precision, "0", "0", "1", "0")
        return initial, certificate

    with localcontext() as context:
        context.prec = precision + 16
        rate = max((-value for value in diagonals), default=Decimal(0))
        if rate == 0:
            rate = Decimal(1)
        transition = _transition_rows(operator, diagonals, rate)
        argument = rate * time
        with localcontext() as bounds:
            bounds.prec = precision + 16
            bounds.rounding = ROUND_CEILING
            transition_norm = max(
                sum((abs(value) for _, value in row), Decimal(0))
                for row in transition
            )
            input_l1 = sum((abs(value) for value in initial), Decimal(0))
        weight = (-argument).exp()
        iterate = initial
        total = tuple(weight * value for value in iterate)
        for term_index in range(max_terms):
            bound = _tail_upper(input_l1, argument, transition_norm, term_index, precision)
            if bound <= tolerance:
                with localcontext() as rounded:
                    rounded.prec = precision
                    output = tuple(+value for value in total)
                    certified = +bound
                return output, TruncationCertificate(
                    term_index,
                    precision,
                    str(rate),
                    str(argument),
                    str(transition_norm),
                    str(certified),
                )
            next_index = term_index + 1
            iterate = _row_action(iterate, transition)
            weight = weight * argument / Decimal(next_index)
            total = tuple(left + weight * right for left, right in zip(total, iterate, strict=True))
    raise UniformizationError("max_terms reached before the truncation bound met tolerance")
