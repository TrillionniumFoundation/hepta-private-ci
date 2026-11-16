import ast
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_fp64_input_bridge.bridge import (
    Fp64UniformizationBridgeError,
    uniformization_action_from_fp64,
)


ROOT = Path(__file__).parent


class ExactFp64UniformizationInputBridgeTest(unittest.TestCase):
    def test_two_state_absorption_uses_only_exact_hex_inputs(self):
        output, certificate = uniformization_action_from_fp64(
            (((0, "bff0000000000000"), (1, "3ff0000000000000")), ()),
            ("3ff0000000000000", "0000000000000000"),
            "3fe0000000000000",
            "39b0000000000000",
            precision=96,
        )
        with localcontext() as context:
            context.prec = 80
            survivor = Decimal("-0.5").exp()
            absorbed = Decimal(1) - survivor
        self.assertLess(abs(output[0] - survivor), Decimal(2) ** -100)
        self.assertLess(abs(output[1] - absorbed), Decimal(2) ** -100)
        self.assertEqual(certificate.operator_value_conversions, 2)
        self.assertEqual(certificate.vector_value_conversions, 2)
        self.assertEqual(certificate.scalar_conversions, 2)
        self.assertEqual(len(certificate.conversion_certificates), 6)
        self.assertTrue(certificate.exact_fp64_input_bridge_certified)
        self.assertFalse(certificate.uniformization_output_rounding_certified)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.provider_qualified)

    def test_signed_vector_and_zero_duration_preserve_bridge_boundaries(self):
        rows = (((0, "c000000000000000"), (1, "4000000000000000")), ())
        signed, signed_certificate = uniformization_action_from_fp64(
            rows,
            ("3ff4000000000000", "bfd0000000000000"),
            "3fc0000000000000",
            "3870000000000000",
            precision=112,
        )
        self.assertLess(abs(sum(signed) - Decimal(1)), Decimal(2) ** -120)
        self.assertLessEqual(
            Decimal(signed_certificate.truncation_certificate.truncation_l1_upper_bound),
            Decimal(2) ** -120,
        )
        unchanged, zero_certificate = uniformization_action_from_fp64(
            rows,
            ("3ff4000000000000", "bfd0000000000000"),
            "8000000000000000",
            "39b0000000000000",
        )
        self.assertEqual(unchanged, (Decimal("1.25"), Decimal("-0.25")))
        self.assertEqual(zero_certificate.truncation_certificate.terms, 0)
        self.assertEqual(
            zero_certificate.conversion_certificates[-2].exact_decimal,
            "-0",
        )

    def test_rejects_noncanonical_or_outside_primitive_domain(self):
        rows = (((0, "bff0000000000000"), (1, "3ff0000000000000")), ())
        with self.assertRaisesRegex(Fp64UniformizationBridgeError, "lowercase hex"):
            uniformization_action_from_fp64(
                rows,
                ("3FF0000000000000", "0000000000000000"),
                "3fe0000000000000",
                "39b0000000000000",
            )
        with self.assertRaisesRegex(Fp64UniformizationBridgeError, "non-finite"):
            uniformization_action_from_fp64(
                rows,
                ("3ff0000000000000", "0000000000000000"),
                "7ff0000000000000",
                "39b0000000000000",
            )
        with self.assertRaisesRegex(Fp64UniformizationBridgeError, "non-negative"):
            uniformization_action_from_fp64(
                rows,
                ("3ff0000000000000", "0000000000000000"),
                "bfe0000000000000",
                "39b0000000000000",
            )
        with self.assertRaisesRegex(Fp64UniformizationBridgeError, "tolerance positive"):
            uniformization_action_from_fp64(
                rows,
                ("3ff0000000000000", "0000000000000000"),
                "3fe0000000000000",
                "0000000000000000",
            )

    def test_bridge_source_does_not_construct_float_or_import_numeric_kernels(self):
        source = (ROOT / "bridge.py").read_text(encoding="utf-8")
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

