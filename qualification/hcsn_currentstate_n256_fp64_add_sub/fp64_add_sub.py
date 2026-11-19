"""Single-operation IEEE-754 binary64 addition and subtraction.

Finite operands are decoded to exact integer ratios through the frozen Draft
#6321 decoder. One exact sum or difference is then rounded by the frozen
Draft #6320 roundTiesToEven primitive. This does not certify FMA or any
multi-operation evaluation sequence.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_fp64_mul_div.fp64_mul_div import (
    Fp64MulDivError,
    _decode_finite_fp64_hex,
)
from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    exact_rational_to_fp64_hex,
)


class Fp64AddSubError(ValueError):
    """Raised when an input is outside the finite add/sub source contract."""


@dataclass(frozen=True)
class Fp64AddSubCertificate:
    operation: str
    lhs_hex: str
    rhs_hex: str
    exact_numerator: str
    exact_denominator: str
    exact_negative_zero: bool
    output_hex: str
    output_category: str
    output_inexact: bool
    rounding_mode: str = "roundTiesToEven"
    finite_add_sub_single_round_certified: bool = True
    fma_and_operator_sequence_certified: bool = False
    n256_provider_qualified: bool = False


def binary64_add_sub(lhs_hex, rhs_hex, operation):
    """Round one finite binary64 addition or subtraction exactly once."""

    if operation not in {"add", "subtract"}:
        raise Fp64AddSubError("operation must be 'add' or 'subtract'")
    try:
        lhs_num, lhs_den, lhs_negative, _ = _decode_finite_fp64_hex(lhs_hex)
        rhs_num, rhs_den, rhs_negative, _ = _decode_finite_fp64_hex(rhs_hex)
    except Fp64MulDivError as error:
        raise Fp64AddSubError(str(error)) from error

    if operation == "subtract":
        rhs_num = -rhs_num
        effective_rhs_negative = not rhs_negative
    else:
        effective_rhs_negative = rhs_negative

    numerator = lhs_num * rhs_den + rhs_num * lhs_den
    denominator = lhs_den * rhs_den
    negative_zero = numerator == 0 and lhs_negative and effective_rhs_negative
    output_hex, rounding = exact_rational_to_fp64_hex(
        numerator,
        denominator,
        negative_zero=negative_zero,
    )
    certificate = Fp64AddSubCertificate(
        operation=operation,
        lhs_hex=lhs_hex,
        rhs_hex=rhs_hex,
        exact_numerator=str(numerator),
        exact_denominator=str(denominator),
        exact_negative_zero=negative_zero,
        output_hex=output_hex,
        output_category=rounding.category,
        output_inexact=rounding.inexact,
    )
    return output_hex, certificate
