import ast
import json
import struct
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_fp64_sequence.fp64_sequence import (
    Fp64SequenceError,
    binary64_evaluate_sequence,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class ExactFp64SequenceTest(unittest.TestCase):
    def test_explicit_instruction_order_and_rounding(self):
        inputs = {
            "a": "3ff8000000000000",
            "b": "4000000000000000",
            "c": "3fe0000000000000",
            "d": "4010000000000000",
        }
        instructions = [
            {"op": "multiply", "dst": "p", "lhs": "a", "rhs": "b"},
            {"op": "add", "dst": "s", "lhs": "p", "rhs": "c"},
            {"op": "divide", "dst": "q", "lhs": "s", "rhs": "d"},
            {"op": "subtract", "dst": "z", "lhs": "q", "rhs": "c"},
        ]
        registers, certificate = binary64_evaluate_sequence(inputs, instructions)
        expected_values = [1.5 * 2.0, 1.5 * 2.0 + 0.5, (1.5 * 2.0 + 0.5) / 4.0, (1.5 * 2.0 + 0.5) / 4.0 - 0.5]
        for name, value in zip(("p", "s", "q", "z"), expected_values):
            self.assertEqual(registers[name], _hex(value))
        self.assertEqual(tuple(step.index for step in certificate.steps), (0, 1, 2, 3))
        self.assertTrue(certificate.explicit_finite_sequence_certified)
        self.assertFalse(certificate.arbitrary_program_certified)
        self.assertFalse(certificate.n256_provider_qualified)

    def test_fma_and_two_rounded_programs_remain_distinct(self):
        inputs = {
            "a": "3ff0000000000001",
            "b": "3ff0000000000001",
            "c": "bff0000000000002",
        }
        fused, _ = binary64_evaluate_sequence(
            inputs,
            [{"op": "fma", "dst": "out", "multiplicand": "a", "multiplier": "b", "addend": "c"}],
        )
        rounded, _ = binary64_evaluate_sequence(
            inputs,
            [
                {"op": "multiply", "dst": "p", "lhs": "a", "rhs": "b"},
                {"op": "add", "dst": "out", "lhs": "p", "rhs": "c"},
            ],
        )
        self.assertEqual(fused["out"], "3970000000000000")
        self.assertEqual(rounded["out"], "0000000000000000")

    def test_rejections_do_not_publish_partial_results(self):
        valid = {"a": "3ff0000000000000", "zero": "0000000000000000"}
        cases = (
            ({}, [{"op": "add", "dst": "x", "lhs": "a", "rhs": "a"}]),
            (valid, []),
            ({"bad-name": "3ff0000000000000"}, [{"op": "add", "dst": "x", "lhs": "a", "rhs": "a"}]),
            ({"a": "7ff0000000000000"}, [{"op": "add", "dst": "x", "lhs": "a", "rhs": "a"}]),
            (valid, [{"op": "divide", "dst": "x", "lhs": "a", "rhs": "zero"}]),
            (valid, [{"op": "add", "dst": "x", "lhs": "missing", "rhs": "a"}]),
            (valid, [{"op": "sqrt", "dst": "x", "lhs": "a"}]),
            (valid, [{"op": "add", "dst": "x", "lhs": "a", "rhs": "a", "extra": "a"}]),
            ({"a": "7fefffffffffffff", "two": "4000000000000000"}, [{"op": "multiply", "dst": "x", "lhs": "a", "rhs": "two"}]),
        )
        for inputs, instructions in cases:
            with self.subTest(inputs=inputs, instructions=instructions):
                with self.assertRaises(Fp64SequenceError):
                    binary64_evaluate_sequence(inputs, instructions)

    def test_certificate_json_and_source_independence(self):
        registers, certificate = binary64_evaluate_sequence(
            {"a": "3ff0000000000000", "b": "4000000000000000"},
            [{"op": "multiply", "dst": "out", "lhs": "a", "rhs": "b"}],
        )
        payload = json.loads(
            json.dumps(
                {"registers": registers, "certificate": certificate.__dict__},
                default=lambda value: value.__dict__,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        self.assertEqual(payload["certificate"]["rounding_mode"], "roundTiesToEven")

        source = (ROOT / "fp64_sequence.py").read_text(encoding="utf-8")
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
