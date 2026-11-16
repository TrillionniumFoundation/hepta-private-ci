"""Single-operation IEEE-754 binary64 multiplication and division.

Finite binary64 inputs are decoded to exact integer ratios.  Multiplication
or division is performed on those ratios and rounded once by the frozen exact
rational roundTiesToEven primitive from Draft #6320.  Division by either
signed zero is outside this deliberately narrow source contract.
"""

from dataclasses import dataclass

from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    exact_rational_to_fp64_hex,
)


class Fp64MulDivError(ValueError):
    """Raised when an input is outside the finite mul/div source contract."""


@dataclass(frozen=True)
class Fp64MulDivCertificate:
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
    finite_mul_div_single_round_certified: bool = True
    add_sub_fma_sequence_certified: bool = False
    n256_provider_qualified: bool = False


def _decode_finite_fp64_hex(value_hex):
    if not isinstance(value_hex, str):
        raise Fp64MulDivError("binary64 input must be canonical hexadecimal text")
    if len(value_hex) != 16 or value_hex != value_hex.lower():
        raise Fp64MulDivError("binary64 input must be 16 lowercase hexadecimal digits")
    if any(character not in "0123456789abcdef" for character in value_hex):
        raise Fp64MulDivError("binary64 input must be 16 lowercase hexadecimal digits")

    bits = int(value_hex, 16)
    sign = bits >> 63
    exponent_bits = (bits >> 52) & 0x7FF
    fraction_bits = bits & ((1 << 52) - 1)
    if exponent_bits == 0x7FF:
        raise Fp64MulDivError("nonfinite binary64 inputs are outside this contract")

    if exponent_bits == 0:
        significand = fraction_bits
        exponent = -1074
    else:
        significand = (1 << 52) | fraction_bits
        exponent = exponent_bits - 1023 - 52

    if exponent >= 0:
        numerator = significand << exponent
        denominator = 1
    else:
        numerator = significand
        denominator = 1 << -exponent
    if sign:
        numerator = -numerator
    return numerator, denominator, bool(sign), significand == 0


def binary64_mul_div(lhs_hex, rhs_hex, operation):
    """Round one finite binary64 multiplication or division exactly once."""

    if operation not in {"multiply", "divide"}:
        raise Fp64MulDivError("operation must be 'multiply' or 'divide'")
    lhs_num, lhs_den, lhs_negative, lhs_zero = _decode_finite_fp64_hex(lhs_hex)
    rhs_num, rhs_den, rhs_negative, rhs_zero = _decode_finite_fp64_hex(rhs_hex)
    if operation == "divide" and rhs_zero:
        raise Fp64MulDivError("division by signed zero is outside this contract")

    negative_zero = (lhs_negative != rhs_negative) and (
        lhs_zero or (operation == "multiply" and rhs_zero)
    )
    if operation == "multiply":
        numerator = lhs_num * rhs_num
        denominator = lhs_den * rhs_den
    else:
        numerator = lhs_num * rhs_den
        denominator = lhs_den * rhs_num
        if denominator < 0:
            numerator = -numerator
            denominator = -denominator

    output_hex, rounding = exact_rational_to_fp64_hex(
        numerator,
        denominator,
        negative_zero=negative_zero,
    )
    certificate = Fp64MulDivCertificate(
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
