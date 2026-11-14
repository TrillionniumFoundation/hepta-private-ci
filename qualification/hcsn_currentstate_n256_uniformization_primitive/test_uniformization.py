import ast
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_primitive.uniformization import (
    UniformizationError,
    uniformization_action,
)


ROOT = Path(__file__).parent


class UniformizationPrimitiveTest(unittest.TestCase):
    def test_two_state_absorption_matches_decimal_closed_form(self):
        result, certificate = uniformization_action(
            (((0, "-1"), (1, "1")), ()),
            ("1", "0"),
            "0.5",
            "1e-60",
        )
        with localcontext() as context:
            context.prec = 80
            survivor = Decimal("-0.5").exp()
            absorbed = Decimal(1) - survivor
        self.assertLess(abs(result[0] - survivor), Decimal("1e-60"))
        self.assertLess(abs(result[1] - absorbed), Decimal("1e-60"))
        self.assertLessEqual(Decimal(certificate.truncation_l1_upper_bound), Decimal("1e-60"))
        self.assertFalse(certificate.finite_precision_rounding_certified)
        self.assertFalse(certificate.n256_provider_qualified)

    def test_signed_vector_bound_and_zero_duration(self):
        rows = (((0, "-2"), (1, "2")), ())
        result, certificate = uniformization_action(rows, ("1.25", "-0.25"), "0.125", "1e-55")
        self.assertLessEqual(Decimal(certificate.truncation_l1_upper_bound), Decimal("1e-55"))
        self.assertLess(abs(sum(result) - Decimal(1)), Decimal("1e-55"))
        unchanged, zero = uniformization_action(rows, ("1.25", "-0.25"), "0", "1e-55")
        self.assertEqual(unchanged, (Decimal("1.25"), Decimal("-0.25")))
        self.assertEqual(zero.terms, 0)

    def test_nonconservative_augmented_selector_is_supported(self):
        result, certificate = uniformization_action(
            (((0, "-1"), (1, "1"), (2, "1")), (), ()),
            ("1", "0", "0"),
            "0.2",
            "1e-55",
        )
        self.assertGreater(Decimal(certificate.transition_l1_norm), Decimal(1))
        self.assertGreater(result[2], Decimal(0))
        self.assertLessEqual(Decimal(certificate.truncation_l1_upper_bound), Decimal("1e-55"))

    def test_rejects_outside_domain_and_insufficient_budget(self):
        with self.assertRaisesRegex(UniformizationError, "off-diagonal"):
            uniformization_action((((0, "-1"), (1, "-0.1")), ()), ("1", "0"), "1", "1e-20")
        with self.assertRaisesRegex(UniformizationError, "max_terms"):
            uniformization_action((((0, "-100"), (1, "100")), ()), ("1", "0"), "10", "1e-60", max_terms=2)

    def test_source_does_not_import_existing_numeric_kernels(self):
        source = (ROOT / "uniformization.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("scipy.sparse.linalg", imported)
        self.assertNotIn("numpy", imported)
        self.assertNotIn("qualification.hcsn_currentstate_n256_sparse_dynamic_intent", source)
        self.assertNotIn("qualification.hcsn_currentstate_n256_independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()
