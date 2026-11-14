"""Single-round finite IEEE-754 binary64 fused multiply-add.

Three finite operands are decoded to exact integer ratios through the frozen
Draft #6321 decoder. The exact product and addend are combined before one
roundTiesToEven boundary through the frozen Draft #6320 primitive. This does
not certify a general multi-operation evaluation sequence.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_fp64_mul_div.fp64_mul_div import (
    Fp64MulDivError,
    _decode_finite_fp64_hex,
)
from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    exact_rational_to_fp64_hex,
)


class Fp64FmaError(ValueError):
    """Raised when an input is outside the finite FMA source contract."""


@dataclass(frozen=True)
class Fp64FmaCertificate:
    multiplicand_hex: str
    multiplier_hex: str
    addend_hex: str
    exact_numerator: str
    exact_denominator: str
    exact_negative_zero: bool
    output_hex: str
    output_category: str
    output_inexact: bool
    rounding_mode: str = "roundTiesToEven"
    finite_fma_single_round_certified: bool = True
    multi_operation_sequence_certified: bool = False
    n256_provider_qualified: bool = False


def binary64_fma(multiplicand_hex, multiplier_hex, addend_hex):
    """Return roundTiesToEven(a * b + c) with no intermediate rounding."""

    try:
        a_num, a_den, a_negative, _ = _decode_finite_fp64_hex(multiplicand_hex)
        b_num, b_den, b_negative, _ = _decode_finite_fp64_hex(multiplier_hex)
        c_num, c_den, c_negative, _ = _decode_finite_fp64_hex(addend_hex)
    except Fp64MulDivError as error:
        raise Fp64FmaError(str(error)) from error

    product_denominator = a_den * b_den
    numerator = a_num * b_num * c_den + c_num * product_denominator
    denominator = product_denominator * c_den
    product_negative = a_negative != b_negative
    negative_zero = numerator == 0 and product_negative and c_negative
    output_hex, rounding = exact_rational_to_fp64_hex(
        numerator,
        denominator,
        negative_zero=negative_zero,
    )
    certificate = Fp64FmaCertificate(
        multiplicand_hex=multiplicand_hex,
        multiplier_hex=multiplier_hex,
        addend_hex=addend_hex,
        exact_numerator=str(numerator),
        exact_denominator=str(denominator),
        exact_negative_zero=negative_zero,
        output_hex=output_hex,
        output_category=rounding.category,
        output_inexact=rounding.inexact,
    )
    return output_hex, certificate
