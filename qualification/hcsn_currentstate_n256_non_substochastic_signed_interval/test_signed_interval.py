import ast
import math
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    non_substochastic_signed_outputs_from_fp64_intervals,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class NonSubstochasticSignedIntervalTest(unittest.TestCase):
    def test_mixed_sign_growing_channel_has_unique_rounding(self):
        rows = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
        outputs, certificate = non_substochastic_signed_outputs_from_fp64_intervals(
            rows,
            ("3ff0000000000000", "bfd0000000000000"),
            "3fe0000000000000",
        )
        survivor = math.exp(-0.5)
        self.assertEqual(outputs, (_hex(survivor), _hex(1.75 - 2 * survivor)))
        self.assertLess(certificate.highest_included_poisson_index, 64)
        self.assertEqual(
            Fraction(
                int(certificate.rate_numerator),
                int(certificate.rate_denominator),
            ),
            Fraction(2),
        )
        self.assertEqual(
            Fraction(
                int(certificate.transition_l1_norm_numerator),
                int(certificate.transition_l1_norm_denominator),
            ),
            Fraction(3, 2),
        )
        self.assertEqual(
            Fraction(
                int(certificate.tail_argument_numerator),
                int(certificate.tail_argument_denominator),
            ),
            Fraction(3, 2),
        )
        self.assertTrue(certificate.exact_signed_rational_interval_certified)
        self.assertTrue(certificate.binary64_unique_rounding_certified)
        self.assertTrue(certificate.nonnegative_transition_certified)
        self.assertTrue(certificate.non_substochastic_transition_certified)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.current_state_provider_qualified)

    def test_negative_outputs_and_zero_duration_are_bounded(self):
        rows = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
        survivor = math.exp(-0.5)
        outputs, certificate = non_substochastic_signed_outputs_from_fp64_intervals(
            rows,
            ("bff0000000000000", "3fd0000000000000"),
            "3fe0000000000000",
        )
        self.assertEqual(outputs, (_hex(-survivor), _hex(-1.75 + 2 * survivor)))
        for interval in certificate.outputs:
            lower = Fraction(int(interval.lower_numerator), int(interval.lower_denominator))
            upper = Fraction(int(interval.upper_numerator), int(interval.upper_denominator))
            self.assertLessEqual(lower, upper)
        unchanged, zero = non_substochastic_signed_outputs_from_fp64_intervals(
            rows,
            ("bff4000000000000", "3fd0000000000000"),
            "8000000000000000",
        )
        self.assertEqual(unchanged, ("bff4000000000000", "3fd0000000000000"))
        self.assertEqual(zero.max_output_interval_width_numerator, "0")

    def test_rejects_substochastic_and_noncanonical_inputs(self):
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "must be non-substochastic"
        ):
            non_substochastic_signed_outputs_from_fp64_intervals(
                (((0, "bff0000000000000"), (1, "3ff0000000000000")), ()),
                ("3ff0000000000000", "bfc0000000000000"),
                "3fe0000000000000",
            )
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "lowercase hex"
        ):
            non_substochastic_signed_outputs_from_fp64_intervals(
                (((0, "bff0000000000000"), (1, "4000000000000000")), ()),
                ("BFF0000000000000", "3fd0000000000000"),
                "3fe0000000000000",
            )

    def test_source_is_stdlib_exact_rational_and_excludes_existing_kernels(self):
        source = (ROOT / "signed_interval.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("float", names)
        self.assertFalse(imported & {"decimal", "numpy", "scipy"})
        self.assertNotIn("uniformization_primitive", source)
        self.assertNotIn("sparse_dynamic_intent", source)
        self.assertNotIn("independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()
