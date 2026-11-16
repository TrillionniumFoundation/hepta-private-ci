import ast
import math
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_output_interval.output_interval import (
    UniformizationOutputIntervalError,
    uniformization_outputs_from_fp64_intervals,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class UniformizationOutputIntervalTest(unittest.TestCase):
    def test_two_state_absorption_has_unique_mathematical_rounding(self):
        outputs, certificate = uniformization_outputs_from_fp64_intervals(
            (((0, "bff0000000000000"), (1, "3ff0000000000000")), ()),
            ("3ff0000000000000", "0000000000000000"),
            "3fe0000000000000",
        )
        survivor = math.exp(-0.5)
        self.assertEqual(outputs, (_hex(survivor), _hex(1.0 - survivor)))
        self.assertLess(certificate.highest_included_poisson_index, 64)
        self.assertTrue(certificate.exact_positive_rational_interval_certified)
        self.assertTrue(certificate.binary64_unique_rounding_certified)
        self.assertFalse(certificate.signed_vector_certified)
        self.assertFalse(certificate.non_substochastic_certified)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.n256_provider_qualified)
        for interval in certificate.outputs:
            lower = Fraction(
                int(interval.lower_numerator),
                int(interval.lower_denominator),
            )
            upper = Fraction(
                int(interval.upper_numerator),
                int(interval.upper_denominator),
            )
            self.assertLessEqual(lower, upper)

    def test_substochastic_escape_and_zero_duration_are_bounded(self):
        rows = (((0, "c000000000000000"), (1, "3ff0000000000000")), ())
        outputs, certificate = uniformization_outputs_from_fp64_intervals(
            rows,
            ("3ff0000000000000", "0000000000000000"),
            "3fd0000000000000",
        )
        survivor = math.exp(-0.5)
        self.assertEqual(outputs, (_hex(survivor), _hex(0.5 * (1.0 - survivor))))
        self.assertGreater(
            Fraction(
                int(certificate.poisson_tail_upper_numerator),
                int(certificate.poisson_tail_upper_denominator),
            ),
            0,
        )
        unchanged, zero = uniformization_outputs_from_fp64_intervals(
            rows,
            ("3ff4000000000000", "3fd0000000000000"),
            "8000000000000000",
        )
        self.assertEqual(unchanged, ("3ff4000000000000", "3fd0000000000000"))
        self.assertEqual(zero.highest_included_poisson_index, 0)
        self.assertEqual(zero.max_output_interval_width_numerator, "0")

    def test_rejects_signed_non_substochastic_and_noncanonical_inputs(self):
        generator = (((0, "bff0000000000000"), (1, "3ff0000000000000")), ())
        with self.assertRaisesRegex(UniformizationOutputIntervalError, "signed vectors"):
            uniformization_outputs_from_fp64_intervals(
                generator,
                ("bff0000000000000", "0000000000000000"),
                "3fe0000000000000",
            )
        with self.assertRaisesRegex(UniformizationOutputIntervalError, "row sum"):
            uniformization_outputs_from_fp64_intervals(
                (((0, "bff0000000000000"), (1, "4000000000000000")), ()),
                ("3ff0000000000000", "0000000000000000"),
                "3fe0000000000000",
            )
        with self.assertRaisesRegex(UniformizationOutputIntervalError, "lowercase hex"):
            uniformization_outputs_from_fp64_intervals(
                generator,
                ("3FF0000000000000", "0000000000000000"),
                "3fe0000000000000",
            )

    def test_source_is_stdlib_exact_rational_and_excludes_existing_kernels(self):
        source = (ROOT / "output_interval.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("float", names)
        self.assertNotIn("decimal", imported)
        self.assertNotIn("numpy", imported)
        self.assertNotIn("scipy", imported)
        self.assertNotIn("uniformization_primitive", source)
        self.assertNotIn("sparse_dynamic_intent", source)
        self.assertNotIn("independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()

