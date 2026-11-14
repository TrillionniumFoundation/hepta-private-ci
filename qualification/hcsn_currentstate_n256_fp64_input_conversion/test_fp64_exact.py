import ast
import json
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_input_conversion.fp64_exact import (
    Fp64InputError,
    fp64_hex_to_exact_decimal,
)


ROOT = Path(__file__).parent


def _fraction_from_decimal(text):
    sign = -1 if text.startswith("-") else 1
    unsigned = text.removeprefix("-")
    if "." not in unsigned:
        return Fraction(sign * int(unsigned), 1)
    whole, fraction = unsigned.split(".")
    denominator = 10 ** len(fraction)
    return Fraction(sign * (int(whole) * denominator + int(fraction)), denominator)


def _fraction_from_certificate(certificate):
    return Fraction(
        int(certificate.exact_numerator),
        1 << certificate.denominator_power_of_two,
    )


class ExactFp64InputConversionTest(unittest.TestCase):
    def test_known_normal_and_signed_zero_values(self):
        cases = {
            "0000000000000000": ("0", "zero"),
            "8000000000000000": ("-0", "zero"),
            "3ff0000000000000": ("1", "normal"),
            "c004000000000000": ("-2.5", "normal"),
            "3fb999999999999a": ("0.1000000000000000055511151231257827021181583404541015625", "normal"),
        }
        for input_hex, expected in cases.items():
            with self.subTest(input_hex=input_hex):
                decimal, certificate = fp64_hex_to_exact_decimal(input_hex)
                self.assertEqual((decimal, certificate.category), expected)
                self.assertEqual(certificate.input_hex, input_hex)
                self.assertTrue(certificate.input_conversion_certified)
                self.assertFalse(certificate.finite_precision_rounding_certified)
                self.assertFalse(certificate.n256_provider_qualified)

    def test_subnormal_and_largest_finite_are_exact(self):
        for input_hex in ("0000000000000001", "000fffffffffffff", "7fefffffffffffff"):
            with self.subTest(input_hex=input_hex):
                decimal, certificate = fp64_hex_to_exact_decimal(input_hex)
                reference = Fraction.from_float(struct.unpack(">d", bytes.fromhex(input_hex))[0])
                self.assertEqual(_fraction_from_decimal(decimal), reference)
                self.assertEqual(_fraction_from_certificate(certificate), reference)
        smallest, certificate = fp64_hex_to_exact_decimal("0000000000000001")
        self.assertEqual(certificate.denominator_power_of_two, 1074)
        self.assertEqual(len(smallest.split(".")[1]), 1074)

    def test_certificate_roundtrips_as_canonical_json(self):
        decimal, certificate = fp64_hex_to_exact_decimal("bff8000000000000")
        payload = json.dumps(certificate.__dict__, sort_keys=True, separators=(",", ":"))
        restored = json.loads(payload)
        self.assertEqual(decimal, "-1.5")
        self.assertEqual(restored["exact_decimal"], decimal)
        self.assertEqual(restored["fraction_bits_hex"], "8000000000000")

    def test_rejects_noncanonical_and_nonfinite_inputs(self):
        for invalid in (
            "0x3ff0000000000000",
            "3FF0000000000000",
            "3ff000000000000",
            "3ff00000000000000",
            "7ff0000000000000",
            "fff0000000000000",
            "7ff8000000000001",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(Fp64InputError):
                    fp64_hex_to_exact_decimal(invalid)

    def test_source_does_not_construct_float_or_import_numeric_kernels(self):
        source = (ROOT / "fp64_exact.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("float", names)
        self.assertNotIn("struct", imported)
        self.assertNotIn("numpy", imported)
        self.assertNotIn("scipy", imported)
        self.assertNotIn("hcsn_currentstate_n256_sparse_dynamic_intent", source)
        self.assertNotIn("hcsn_currentstate_n256_independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()

