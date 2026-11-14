"""Exact conversion of canonical IEEE-754 binary64 bytes into decimal text.

This module never constructs a Python float.  It decodes the canonical
big-endian hexadecimal bytes as integers and emits the finite base-10
expansion of the represented dyadic rational.  It certifies input conversion
only; arithmetic rounding and the N256 reference provider remain separate.
"""

from dataclasses import dataclass


class Fp64InputError(ValueError):
    """Raised when an input is not one canonical finite binary64 value."""


@dataclass(frozen=True)
class Fp64ConversionCertificate:
    input_hex: str
    sign_bit: int
    exponent_bits: int
    fraction_bits_hex: str
    category: str
    exact_numerator: str
    denominator_power_of_two: int
    exact_decimal: str
    input_conversion_certified: bool = True
    finite_precision_rounding_certified: bool = False
    n256_provider_qualified: bool = False


def _canonical_bits(input_hex):
    if not isinstance(input_hex, str) or len(input_hex) != 16:
        raise Fp64InputError("binary64 input must be exactly 16 lowercase hex digits")
    if any(character not in "0123456789abcdef" for character in input_hex):
        raise Fp64InputError("binary64 input must be exactly 16 lowercase hex digits")
    return int(input_hex, 16)


def _exact_decimal(sign, numerator, denominator_power):
    if numerator == 0:
        return "-0" if sign else "0"
    if denominator_power == 0:
        digits = str(numerator)
    else:
        scaled = str(numerator * 5**denominator_power)
        if len(scaled) <= denominator_power:
            scaled = "0" * (denominator_power + 1 - len(scaled)) + scaled
        split = len(scaled) - denominator_power
        digits = f"{scaled[:split]}.{scaled[split:]}"
    return f"-{digits}" if sign else digits


def fp64_hex_to_exact_decimal(input_hex):
    """Decode canonical big-endian binary64 hex without binary float conversion."""

    bits = _canonical_bits(input_hex)
    sign = bits >> 63
    exponent_bits = (bits >> 52) & 0x7FF
    fraction_bits = bits & ((1 << 52) - 1)
    if exponent_bits == 0x7FF:
        raise Fp64InputError("non-finite binary64 values are outside the input domain")

    if exponent_bits == 0:
        if fraction_bits == 0:
            category = "zero"
            numerator = 0
            denominator_power = 0
        else:
            category = "subnormal"
            numerator = fraction_bits
            exponent_two = -1074
            while numerator % 2 == 0:
                numerator //= 2
                exponent_two += 1
            denominator_power = -exponent_two
    else:
        category = "normal"
        numerator = (1 << 52) | fraction_bits
        exponent_two = exponent_bits - 1023 - 52
        while exponent_two < 0 and numerator % 2 == 0:
            numerator //= 2
            exponent_two += 1
        if exponent_two >= 0:
            numerator <<= exponent_two
            denominator_power = 0
        else:
            denominator_power = -exponent_two

    signed_numerator = -numerator if sign and numerator else numerator
    exact_decimal = _exact_decimal(sign, numerator, denominator_power)
    certificate = Fp64ConversionCertificate(
        input_hex=input_hex,
        sign_bit=sign,
        exponent_bits=exponent_bits,
        fraction_bits_hex=f"{fraction_bits:013x}",
        category=category,
        exact_numerator=str(signed_numerator),
        denominator_power_of_two=denominator_power,
        exact_decimal=exact_decimal,
    )
    return exact_decimal, certificate

