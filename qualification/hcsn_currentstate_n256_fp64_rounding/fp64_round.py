"""Round exact rational values to IEEE-754 binary64 using integer arithmetic.

The implementation has no binary floating-point dependency.  It implements
roundTiesToEven across zero, subnormal, normal, carry, and overflow boundaries.
This is a rounding primitive only; it does not certify an N256 operator or
reference-provider execution.
"""

from dataclasses import dataclass


class Fp64RoundingError(ValueError):
    """Raised when the exact rational input is outside the source contract."""


@dataclass(frozen=True)
class Fp64RoundingCertificate:
    exact_numerator: str
    exact_denominator: str
    negative_zero: bool
    output_hex: str
    category: str
    sign_bit: int
    exponent_bits: int
    fraction_bits_hex: str
    inexact: bool
    rounding_mode: str = "roundTiesToEven"
    rational_to_binary64_rounding_certified: bool = True
    operator_arithmetic_rounding_certified: bool = False
    n256_provider_qualified: bool = False


def _round_ties_to_even(numerator, denominator):
    quotient, remainder = divmod(numerator, denominator)
    twice_remainder = remainder << 1
    if twice_remainder > denominator or (
        twice_remainder == denominator and quotient & 1
    ):
        quotient += 1
    return quotient, remainder != 0


def _floor_log2_ratio(numerator, denominator):
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    return exponent


def _scaled_round(numerator, denominator, shift):
    if shift >= 0:
        return _round_ties_to_even(numerator << shift, denominator)
    return _round_ties_to_even(numerator, denominator << -shift)


def exact_rational_to_fp64_hex(numerator, denominator, *, negative_zero=False):
    """Return canonical big-endian binary64 hex and an exact rounding certificate."""

    if isinstance(numerator, bool) or not isinstance(numerator, int):
        raise Fp64RoundingError("numerator must be an integer")
    if isinstance(denominator, bool) or not isinstance(denominator, int):
        raise Fp64RoundingError("denominator must be a positive integer")
    if denominator <= 0:
        raise Fp64RoundingError("denominator must be a positive integer")
    if not isinstance(negative_zero, bool):
        raise Fp64RoundingError("negative_zero must be boolean")
    if numerator != 0 and negative_zero:
        raise Fp64RoundingError("negative_zero is valid only for an exact zero")

    sign = 1 if numerator < 0 or (numerator == 0 and negative_zero) else 0
    magnitude = abs(numerator)
    if magnitude == 0:
        exponent_bits = 0
        fraction_bits = 0
        category = "zero"
        inexact = False
    else:
        exponent = _floor_log2_ratio(magnitude, denominator)
        if exponent < -1022:
            significand, inexact = _scaled_round(magnitude, denominator, 1074)
            if significand == 0:
                exponent_bits = 0
                fraction_bits = 0
                category = "zero"
            elif significand < 1 << 52:
                exponent_bits = 0
                fraction_bits = significand
                category = "subnormal"
            else:
                exponent_bits = 1
                fraction_bits = 0
                category = "normal"
        elif exponent >= 1024:
            exponent_bits = 0x7FF
            fraction_bits = 0
            category = "infinity"
            inexact = True
        else:
            significand, inexact = _scaled_round(
                magnitude,
                denominator,
                52 - exponent,
            )
            if significand == 1 << 53:
                significand >>= 1
                exponent += 1
            if exponent >= 1024:
                exponent_bits = 0x7FF
                fraction_bits = 0
                category = "infinity"
                inexact = True
            else:
                exponent_bits = exponent + 1023
                fraction_bits = significand - (1 << 52)
                category = "normal"

    bits = (sign << 63) | (exponent_bits << 52) | fraction_bits
    output_hex = f"{bits:016x}"
    certificate = Fp64RoundingCertificate(
        exact_numerator=str(numerator),
        exact_denominator=str(denominator),
        negative_zero=negative_zero,
        output_hex=output_hex,
        category=category,
        sign_bit=sign,
        exponent_bits=exponent_bits,
        fraction_bits_hex=f"{fraction_bits:013x}",
        inexact=inexact,
    )
    return output_hex, certificate

