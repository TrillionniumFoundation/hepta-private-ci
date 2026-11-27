import ast
import json
import random
import struct
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_mul_div.fp64_mul_div import (
    Fp64MulDivError,
    binary64_mul_div,
)


ROOT = Path(__file__).parent


def _as_float(value_hex):
    return struct.unpack(">d", bytes.fromhex(value_hex))[0]


def _as_hex(value):
    return struct.pack(">d", value).hex()


def _reference(lhs_hex, rhs_hex, operation):
    lhs = _as_float(lhs_hex)
    rhs = _as_float(rhs_hex)
    if operation == "multiply":
        return _as_hex(lhs * rhs)
    return _as_hex(lhs / rhs)


class ExactFp64MulDivTest(unittest.TestCase):
    def test_known_multiplication_boundaries_and_signed_zero(self):
        cases = (
            ("3ff8000000000000", "4000000000000000", "4008000000000000"),
            ("3fb999999999999a", "3fc999999999999a", "3f947ae147ae147c"),
            ("0010000000000000", "3fe0000000000000", "0008000000000000"),
            ("0000000000000001", "3fe0000000000000", "0000000000000000"),
            ("7fefffffffffffff", "4000000000000000", "7ff0000000000000"),
            ("8000000000000000", "4000000000000000", "8000000000000000"),
            ("8000000000000000", "c000000000000000", "0000000000000000"),
        )
        for lhs_hex, rhs_hex, expected_hex in cases:
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex):
                output_hex, certificate = binary64_mul_div(
                    lhs_hex,
                    rhs_hex,
                    "multiply",
                )
                self.assertEqual(output_hex, expected_hex)
                self.assertTrue(certificate.finite_mul_div_single_round_certified)
                self.assertFalse(certificate.add_sub_fma_sequence_certified)
                self.assertFalse(certificate.n256_provider_qualified)

    def test_known_division_values_and_signed_zero(self):
        cases = (
            ("3ff0000000000000", "4008000000000000", "3fd5555555555555"),
            ("4014000000000000", "4000000000000000", "4004000000000000"),
            ("8000000000000000", "4000000000000000", "8000000000000000"),
            ("8000000000000000", "c000000000000000", "0000000000000000"),
        )
        for lhs_hex, rhs_hex, expected_hex in cases:
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex):
                output_hex, _ = binary64_mul_div(lhs_hex, rhs_hex, "divide")
                self.assertEqual(output_hex, expected_hex)

    def test_deterministic_finite_corpus_matches_hardware_binary64(self):
        generator = random.Random(0xC06D2562)
        comparisons = 0
        for operation in ("multiply", "divide"):
            while comparisons < (512 if operation == "multiply" else 1024):
                lhs_bits = generator.getrandbits(64)
                rhs_bits = generator.getrandbits(64)
                if (lhs_bits >> 52) & 0x7FF == 0x7FF:
                    continue
                if (rhs_bits >> 52) & 0x7FF == 0x7FF:
                    continue
                lhs_hex = f"{lhs_bits:016x}"
                rhs_hex = f"{rhs_bits:016x}"
                if operation == "divide" and rhs_bits & ((1 << 63) - 1) == 0:
                    continue
                output_hex, _ = binary64_mul_div(lhs_hex, rhs_hex, operation)
                self.assertEqual(output_hex, _reference(lhs_hex, rhs_hex, operation))
                comparisons += 1
        self.assertEqual(comparisons, 1024)

    def test_rejections_certificate_json_and_source_independence(self):
        for lhs_hex, rhs_hex, operation in (
            ("7ff0000000000000", "3ff0000000000000", "multiply"),
            ("7ff8000000000000", "3ff0000000000000", "multiply"),
            ("3ff0000000000000", "0000000000000000", "divide"),
            ("3ff0000000000000", "8000000000000000", "divide"),
            ("3FF0000000000000", "3ff0000000000000", "multiply"),
            ("3ff", "3ff0000000000000", "multiply"),
            ("3ff0000000000000", "3ff0000000000000", "add"),
        ):
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex, operation=operation):
                with self.assertRaises(Fp64MulDivError):
                    binary64_mul_div(lhs_hex, rhs_hex, operation)

        _, certificate = binary64_mul_div(
            "3ff0000000000000",
            "4008000000000000",
            "divide",
        )
        payload = json.loads(
            json.dumps(certificate.__dict__, sort_keys=True, separators=(",", ":"))
        )
        self.assertEqual(payload["rounding_mode"], "roundTiesToEven")

        source = (ROOT / "fp64_mul_div.py").read_text(encoding="utf-8")
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
