"""Round exact rationals to binary64 without decimal certificate conversion."""

from fractions import Fraction


class HexOnlyRoundingError(ValueError):
    """Raised when an input is outside the bounded rounding contract."""


def _round_ties_to_even(numerator, denominator):
    quotient, remainder = divmod(numerator, denominator)
    twice_remainder = remainder << 1
    if twice_remainder > denominator or (
        twice_remainder == denominator and quotient & 1
    ):
        quotient += 1
    return quotient


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


def rational_to_fp64_hex_without_decimal_certificate(numerator, denominator):
    """Return canonical binary64 hex using only bounded integer operations."""

    if isinstance(numerator, bool) or not isinstance(numerator, int):
        raise HexOnlyRoundingError("numerator must be an integer")
    if isinstance(denominator, bool) or not isinstance(denominator, int):
        raise HexOnlyRoundingError("denominator must be a positive integer")
    if denominator <= 0:
        raise HexOnlyRoundingError("denominator must be a positive integer")
    sign = int(numerator < 0)
    magnitude = abs(numerator)
    if magnitude == 0:
        exponent_bits = 0
        fraction_bits = 0
    else:
        exponent = _floor_log2_ratio(magnitude, denominator)
        if exponent < -1022:
            significand = _scaled_round(magnitude, denominator, 1074)
            if significand == 0:
                exponent_bits = 0
                fraction_bits = 0
            elif significand < 1 << 52:
                exponent_bits = 0
                fraction_bits = significand
            else:
                exponent_bits = 1
                fraction_bits = 0
        elif exponent >= 1024:
            exponent_bits = 0x7FF
            fraction_bits = 0
        else:
            significand = _scaled_round(magnitude, denominator, 52 - exponent)
            if significand == 1 << 53:
                significand >>= 1
                exponent += 1
            if exponent >= 1024:
                exponent_bits = 0x7FF
                fraction_bits = 0
            else:
                exponent_bits = exponent + 1023
                fraction_bits = significand - (1 << 52)
    bits = (sign << 63) | (exponent_bits << 52) | fraction_bits
    return f"{bits:016x}"


def round_fraction_without_decimal_certificate(value):
    if not isinstance(value, Fraction):
        raise HexOnlyRoundingError("value must be a Fraction")
    return rational_to_fp64_hex_without_decimal_certificate(
        value.numerator,
        value.denominator,
    )
