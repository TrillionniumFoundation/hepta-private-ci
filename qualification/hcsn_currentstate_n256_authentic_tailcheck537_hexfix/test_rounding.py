"""Independent controls for hex-only exact rational rounding."""

from fractions import Fraction
import unittest

from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    exact_rational_to_fp64_hex,
)

from .rounding import (
    HexOnlyRoundingError,
    rational_to_fp64_hex_without_decimal_certificate,
    round_fraction_without_decimal_certificate,
)


class HexOnlyRoundingTests(unittest.TestCase):
    def test_matches_existing_primitive_on_bounded_corpus(self):
        corpus = [
            (0, 1),
            (1, 1),
            (-1, 1),
            (1, 3),
            (2**53 + 1, 2**53),
            (1, 2**1074),
            (1, 2**1075),
            (2**1024, 1),
            (-(2**1024), 1),
        ]
        for numerator, denominator in corpus:
            expected, _ = exact_rational_to_fp64_hex(numerator, denominator)
            actual = rational_to_fp64_hex_without_decimal_certificate(
                numerator,
                denominator,
            )
            self.assertEqual(actual, expected)

    def test_large_exact_input_never_converts_to_decimal(self):
        denominator = 10**5000
        value = Fraction(denominator + 1, denominator)
        self.assertEqual(
            round_fraction_without_decimal_certificate(value),
            "3ff0000000000000",
        )

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaisesRegex(HexOnlyRoundingError, "numerator"):
            rational_to_fp64_hex_without_decimal_certificate(True, 1)
        with self.assertRaisesRegex(HexOnlyRoundingError, "denominator"):
            rational_to_fp64_hex_without_decimal_certificate(1, 0)
        with self.assertRaisesRegex(HexOnlyRoundingError, "Fraction"):
            round_fraction_without_decimal_certificate(1)


if __name__ == "__main__":
    unittest.main()
