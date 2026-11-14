import ast
import math
import struct
import unittest
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_augmented_selector_interval.augmented_selector import (
    augmented_selector_outputs_from_fp64_amplitude,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class AugmentedSelectorIntervalTest(unittest.TestCase):
    def test_positive_augmented_outputs_have_unique_rounding(self):
        outputs, certificate = augmented_selector_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fe0000000000000"
        )
        active = math.exp(-1.5)
        discounted_active = math.exp(-1.75)
        self.assertEqual(
            outputs,
            (
                _hex(active),
                _hex((1 - active) / 3),
                _hex(2 * (1 - active) / 3),
                _hex((1 - active) / 3),
                _hex(discounted_active),
                _hex(4 * (1 - discounted_active) / 7),
                _hex(2 * (1 - discounted_active) / 7),
            ),
        )
        self.assertEqual(
            certificate.state_order,
            (
                "active",
                "nonreturning_upper",
                "lower_hit",
                "occupation",
                "discounted_active",
                "discounted_lower_hit",
                "discounted_occupation",
            ),
        )
        self.assertTrue(certificate.nonreturning_upper_encoded)
        self.assertTrue(certificate.lower_hit_accumulator_encoded)
        self.assertTrue(certificate.occupation_accumulator_encoded)
        self.assertTrue(certificate.discounted_hit_accumulator_encoded)
        self.assertTrue(certificate.discounted_occupation_accumulator_encoded)
        self.assertFalse(certificate.deterministic_delay_encoded)
        self.assertFalse(certificate.reset_encoded)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.current_state_provider_qualified)

    def test_signed_mirror_and_zero_duration_are_exact(self):
        positive, positive_certificate = (
            augmented_selector_outputs_from_fp64_amplitude(
                "3ff0000000000000", "3fe0000000000000"
            )
        )
        negative, negative_certificate = (
            augmented_selector_outputs_from_fp64_amplitude(
                "bff0000000000000", "3fe0000000000000"
            )
        )
        self.assertEqual(
            tuple(bytes.fromhex(value) for value in negative),
            tuple(
                struct.pack(">d", -struct.unpack(">d", bytes.fromhex(value))[0])
                for value in positive
            ),
        )
        self.assertEqual(
            positive_certificate.interval_certificate.highest_included_poisson_index,
            negative_certificate.interval_certificate.highest_included_poisson_index,
        )
        unchanged, zero = augmented_selector_outputs_from_fp64_amplitude(
            "bff0000000000000", "8000000000000000"
        )
        self.assertEqual(
            unchanged,
            (
                "bff0000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "bff0000000000000",
                "0000000000000000",
                "0000000000000000",
            ),
        )
        self.assertEqual(
            Fraction(
                int(zero.interval_certificate.max_output_interval_width_numerator),
                int(zero.interval_certificate.max_output_interval_width_denominator),
            ),
            Fraction(0),
        )

    def test_source_remains_a_small_fail_closed_selector_wrapper(self):
        source = (ROOT / "augmented_selector.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("float", names)
        self.assertFalse(imported & {"decimal", "numpy", "scipy", "torch"})
        self.assertNotIn("sparse_dynamic_intent", source)
        self.assertNotIn("independent_oracle_intent", source)


if __name__ == "__main__":
    unittest.main()
