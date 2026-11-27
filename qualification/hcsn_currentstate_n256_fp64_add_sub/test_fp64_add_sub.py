import ast
import json
import random
import struct
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_add_sub.fp64_add_sub import (
    Fp64AddSubError,
    binary64_add_sub,
)


ROOT = Path(__file__).parent


def _as_float(value_hex):
    return struct.unpack(">d", bytes.fromhex(value_hex))[0]


def _as_hex(value):
    return struct.pack(">d", value).hex()


def _reference(lhs_hex, rhs_hex, operation):
    lhs = _as_float(lhs_hex)
    rhs = _as_float(rhs_hex)
    if operation == "add":
        return _as_hex(lhs + rhs)
    return _as_hex(lhs - rhs)


class ExactFp64AddSubTest(unittest.TestCase):
    def test_known_addition_rounding_and_zero_signs(self):
        cases = (
            ("3ff0000000000000", "bff0000000000000", "0000000000000000"),
            ("8000000000000000", "8000000000000000", "8000000000000000"),
            ("0000000000000000", "8000000000000000", "0000000000000000"),
            ("0000000000000001", "0000000000000001", "0000000000000002"),
            ("3ff0000000000000", "3ca0000000000000", "3ff0000000000000"),
            ("3ff0000000000000", "3cb8000000000000", "3ff0000000000002"),
            ("7fefffffffffffff", "7fefffffffffffff", "7ff0000000000000"),
        )
        for lhs_hex, rhs_hex, expected_hex in cases:
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex):
                output_hex, certificate = binary64_add_sub(lhs_hex, rhs_hex, "add")
                self.assertEqual(output_hex, expected_hex)
                self.assertTrue(certificate.finite_add_sub_single_round_certified)
                self.assertFalse(certificate.fma_and_operator_sequence_certified)
                self.assertFalse(certificate.n256_provider_qualified)

    def test_known_subtraction_rounding_and_zero_signs(self):
        cases = (
            ("3ff0000000000000", "3ff0000000000000", "0000000000000000"),
            ("8000000000000000", "0000000000000000", "8000000000000000"),
            ("0000000000000000", "8000000000000000", "0000000000000000"),
            ("0010000000000000", "000fffffffffffff", "0000000000000001"),
            ("bff0000000000000", "bff0000000000000", "0000000000000000"),
        )
        for lhs_hex, rhs_hex, expected_hex in cases:
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex):
                output_hex, _ = binary64_add_sub(lhs_hex, rhs_hex, "subtract")
                self.assertEqual(output_hex, expected_hex)

    def test_deterministic_finite_corpus_matches_hardware_binary64(self):
        generator = random.Random(0xC06D2563)
        comparisons = 0
        for operation in ("add", "subtract"):
            target = comparisons + 512
            while comparisons < target:
                lhs_bits = generator.getrandbits(64)
                rhs_bits = generator.getrandbits(64)
                if (lhs_bits >> 52) & 0x7FF == 0x7FF:
                    continue
                if (rhs_bits >> 52) & 0x7FF == 0x7FF:
                    continue
                lhs_hex = f"{lhs_bits:016x}"
                rhs_hex = f"{rhs_bits:016x}"
                output_hex, _ = binary64_add_sub(lhs_hex, rhs_hex, operation)
                self.assertEqual(output_hex, _reference(lhs_hex, rhs_hex, operation))
                comparisons += 1
        self.assertEqual(comparisons, 1024)

    def test_rejections_certificate_json_and_source_independence(self):
        for lhs_hex, rhs_hex, operation in (
            ("7ff0000000000000", "3ff0000000000000", "add"),
            ("7ff8000000000000", "3ff0000000000000", "subtract"),
            ("3FF0000000000000", "3ff0000000000000", "add"),
            ("3ff", "3ff0000000000000", "add"),
            ("3ff0000000000000", "3ff0000000000000", "multiply"),
        ):
            with self.subTest(lhs_hex=lhs_hex, rhs_hex=rhs_hex, operation=operation):
                with self.assertRaises(Fp64AddSubError):
                    binary64_add_sub(lhs_hex, rhs_hex, operation)

        _, certificate = binary64_add_sub(
            "3ff0000000000000",
            "3ca0000000000000",
            "add",
        )
        payload = json.loads(
            json.dumps(certificate.__dict__, sort_keys=True, separators=(",", ":"))
        )
        self.assertEqual(payload["rounding_mode"], "roundTiesToEven")

        source = (ROOT / "fp64_add_sub.py").read_text(encoding="utf-8")
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
