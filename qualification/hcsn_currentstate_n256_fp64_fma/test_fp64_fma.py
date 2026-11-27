import ast
import json
import math
import random
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_fma.fp64_fma import (
    Fp64FmaError,
    binary64_fma,
)


ROOT = Path(__file__).parent


def _as_float(value_hex):
    return struct.unpack(">d", bytes.fromhex(value_hex))[0]


def _as_hex(value):
    return struct.pack(">d", value).hex()


def _reference(a_hex, b_hex, c_hex):
    a = _as_float(a_hex)
    b = _as_float(b_hex)
    c = _as_float(c_hex)
    exact = Fraction.from_float(a) * Fraction.from_float(b) + Fraction.from_float(c)
    if exact == 0:
        product_negative = math.copysign(1.0, a) != math.copysign(1.0, b)
        addend_negative = math.copysign(1.0, c) < 0
        return "8000000000000000" if product_negative and addend_negative else "0000000000000000"
    try:
        return _as_hex(float(exact))
    except OverflowError:
        return "fff0000000000000" if exact < 0 else "7ff0000000000000"


class ExactFp64FmaTest(unittest.TestCase):
    def test_known_single_rounding_and_zero_signs(self):
        cases = (
            ("3ff8000000000000", "4000000000000000", "3fe0000000000000", "400c000000000000"),
            ("3ff0000000000001", "3ff0000000000001", "bff0000000000002", "3970000000000000"),
            ("8000000000000000", "4000000000000000", "8000000000000000", "8000000000000000"),
            ("8000000000000000", "4000000000000000", "0000000000000000", "0000000000000000"),
            ("3ff0000000000000", "3ff0000000000000", "bff0000000000000", "0000000000000000"),
            ("0000000000000001", "3fe0000000000000", "0000000000000000", "0000000000000000"),
            ("7fefffffffffffff", "4000000000000000", "0000000000000000", "7ff0000000000000"),
        )
        for a_hex, b_hex, c_hex, expected_hex in cases:
            with self.subTest(a_hex=a_hex, b_hex=b_hex, c_hex=c_hex):
                output_hex, certificate = binary64_fma(a_hex, b_hex, c_hex)
                self.assertEqual(output_hex, expected_hex)
                self.assertTrue(certificate.finite_fma_single_round_certified)
                self.assertFalse(certificate.multi_operation_sequence_certified)
                self.assertFalse(certificate.n256_provider_qualified)

    def test_fused_case_differs_from_two_rounded_operations(self):
        a_hex = "3ff0000000000001"
        b_hex = "3ff0000000000001"
        c_hex = "bff0000000000002"
        fused_hex, _ = binary64_fma(a_hex, b_hex, c_hex)
        nonfused_hex = _as_hex(_as_float(a_hex) * _as_float(b_hex) + _as_float(c_hex))
        self.assertEqual(fused_hex, "3970000000000000")
        self.assertEqual(nonfused_hex, "0000000000000000")

    def test_deterministic_finite_corpus_matches_fraction_reference(self):
        generator = random.Random(0xC06D2564)
        comparisons = 0
        while comparisons < 512:
            bits = [generator.getrandbits(64) for _ in range(3)]
            if any(((value >> 52) & 0x7FF) == 0x7FF for value in bits):
                continue
            values = [f"{value:016x}" for value in bits]
            output_hex, _ = binary64_fma(*values)
            self.assertEqual(output_hex, _reference(*values))
            comparisons += 1
        self.assertEqual(comparisons, 512)

    def test_rejections_certificate_json_and_source_independence(self):
        for values in (
            ("7ff0000000000000", "3ff0000000000000", "0000000000000000"),
            ("3ff0000000000000", "7ff8000000000000", "0000000000000000"),
            ("3ff0000000000000", "3ff0000000000000", "fff0000000000000"),
            ("3FF0000000000000", "3ff0000000000000", "0000000000000000"),
            ("3ff", "3ff0000000000000", "0000000000000000"),
        ):
            with self.subTest(values=values):
                with self.assertRaises(Fp64FmaError):
                    binary64_fma(*values)

        _, certificate = binary64_fma(
            "3ff8000000000000",
            "4000000000000000",
            "3fe0000000000000",
        )
        payload = json.loads(
            json.dumps(certificate.__dict__, sort_keys=True, separators=(",", ":"))
        )
        self.assertEqual(payload["rounding_mode"], "roundTiesToEven")

        source = (ROOT / "fp64_fma.py").read_text(encoding="utf-8")
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
