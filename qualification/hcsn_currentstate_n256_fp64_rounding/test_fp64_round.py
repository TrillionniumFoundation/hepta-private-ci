import ast
import json
import random
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_rounding.fp64_round import (
    Fp64RoundingError,
    exact_rational_to_fp64_hex,
)


ROOT = Path(__file__).parent


def _python_reference(numerator, denominator):
    value = float(Fraction(numerator, denominator))
    return struct.pack(">d", value).hex()


class ExactFp64RoundingTest(unittest.TestCase):
    def test_exact_values_and_signed_zero(self):
        cases = (
            (0, 1, False, "0000000000000000", "zero"),
            (0, 7, True, "8000000000000000", "zero"),
            (1, 1, False, "3ff0000000000000", "normal"),
            (-5, 2, False, "c004000000000000", "normal"),
            (1, 10, False, "3fb999999999999a", "normal"),
            (1, 1 << 1074, False, "0000000000000001", "subnormal"),
        )
        for numerator, denominator, negative_zero, expected_hex, category in cases:
            with self.subTest(expected_hex=expected_hex):
                output_hex, certificate = exact_rational_to_fp64_hex(
                    numerator,
                    denominator,
                    negative_zero=negative_zero,
                )
                self.assertEqual((output_hex, certificate.category), (expected_hex, category))
                self.assertTrue(certificate.rational_to_binary64_rounding_certified)
                self.assertFalse(certificate.operator_arithmetic_rounding_certified)
                self.assertFalse(certificate.n256_provider_qualified)

    def test_rounds_midpoints_to_even_at_normal_and_subnormal_boundaries(self):
        cases = (
            ((1 << 53) + 1, 1 << 53, "3ff0000000000000"),
            ((1 << 53) + 3, 1 << 53, "3ff0000000000002"),
            (1, 1 << 1075, "0000000000000000"),
            (3, 1 << 1075, "0000000000000002"),
            ((1 << 53) - 1, 1 << 1075, "0010000000000000"),
        )
        for numerator, denominator, expected_hex in cases:
            with self.subTest(expected_hex=expected_hex):
                output_hex, certificate = exact_rational_to_fp64_hex(numerator, denominator)
                self.assertEqual(output_hex, expected_hex)
                self.assertTrue(certificate.inexact)

    def test_normal_carry_and_overflow_boundary(self):
        max_finite_numerator = ((1 << 53) - 1) << 971
        output_hex, certificate = exact_rational_to_fp64_hex(max_finite_numerator, 1)
        self.assertEqual(output_hex, "7fefffffffffffff")
        self.assertFalse(certificate.inexact)
        overflow_midpoint = ((1 << 54) - 1) << 970
        output_hex, certificate = exact_rational_to_fp64_hex(overflow_midpoint, 1)
        self.assertEqual(output_hex, "7ff0000000000000")
        self.assertEqual(certificate.category, "infinity")
        self.assertTrue(certificate.inexact)

    def test_deterministic_rational_corpus_matches_test_only_python_reference(self):
        generator = random.Random(0xC06D256)
        comparisons = 0
        for _ in range(512):
            numerator = generator.randrange(-(1 << 180), 1 << 180)
            denominator = generator.randrange(1, 1 << 170)
            output_hex, _ = exact_rational_to_fp64_hex(numerator, denominator)
            self.assertEqual(output_hex, _python_reference(numerator, denominator))
            comparisons += 1
        self.assertEqual(comparisons, 512)

    def test_certificate_json_rejections_and_source_independence(self):
        _, certificate = exact_rational_to_fp64_hex(-1, 10)
        payload = json.dumps(certificate.__dict__, sort_keys=True, separators=(",", ":"))
        self.assertEqual(json.loads(payload)["rounding_mode"], "roundTiesToEven")
        for args in ((True, 1), (1, False), (1, 0), (1, -1)):
            with self.subTest(args=args):
                with self.assertRaises(Fp64RoundingError):
                    exact_rational_to_fp64_hex(*args)
        with self.assertRaises(Fp64RoundingError):
            exact_rational_to_fp64_hex(1, 1, negative_zero=True)
        with self.assertRaises(Fp64RoundingError):
            exact_rational_to_fp64_hex(0, 1, negative_zero=1)

        source = (ROOT / "fp64_round.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("float", names)
        self.assertNotIn("struct", imported)
        self.assertNotIn("fractions", imported)
        self.assertNotIn("numpy", imported)
        self.assertNotIn("scipy", imported)
        self.assertNotIn("hcsn_currentstate_n256_sparse_dynamic_intent", source)
        self.assertNotIn("hcsn_currentstate_n256_independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()

