import ast
import struct
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from qualification.hcsn_currentstate_scheduled_reset_interval.scheduled_reset import (
    scheduled_reset_outputs_from_fp64_amplitude,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class ScheduledResetIntervalTest(unittest.TestCase):
    def test_two_segment_scheduled_reset_has_unique_rounding(self):
        outputs, certificate = scheduled_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        with localcontext() as context:
            context.prec = 100
            one = Decimal(1)
            active_decay = Decimal("-0.75").exp()
            reset_active = (2 + active_decay) / 3
            discounted_decay = Decimal("-0.875").exp()
            reset_discounted_active = (4 + 3 * discounted_decay) / 7
            expected = (
                _hex(float(reset_active * active_decay)),
                _hex(float((one - active_decay) / 3 + reset_active * (one - active_decay) / 3)),
                _hex(float(reset_active * 2 * (one - active_decay) / 3)),
                _hex(float((one - active_decay) / 3 + reset_active * (one - active_decay) / 3)),
                _hex(float(reset_discounted_active * discounted_decay)),
                _hex(float(reset_discounted_active * 4 * (one - discounted_decay) / 7)),
                _hex(float(2 * (one - discounted_decay) / 7 + reset_discounted_active * 2 * (one - discounted_decay) / 7)),
            )
        self.assertEqual(
            outputs,
            expected,
        )
        self.assertTrue(certificate.reset_at_fixed_schedule_encoded)
        self.assertTrue(certificate.full_interval_state_propagated)
        self.assertFalse(certificate.hit_specific_deterministic_delay_encoded)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.current_state_provider_qualified)
        self.assertLess(certificate.second_segment.highest_included_poisson_index, 64)

    def test_signed_mirror_and_zero_schedule_remain_exact(self):
        positive, positive_certificate = scheduled_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        negative, negative_certificate = scheduled_reset_outputs_from_fp64_amplitude(
            "bff0000000000000", "3fd0000000000000"
        )
        self.assertEqual(
            tuple(bytes.fromhex(value) for value in negative),
            tuple(
                struct.pack(">d", -struct.unpack(">d", bytes.fromhex(value))[0])
                for value in positive
            ),
        )
        self.assertEqual(
            positive_certificate.second_segment.highest_included_poisson_index,
            negative_certificate.second_segment.highest_included_poisson_index,
        )
        unchanged, zero = scheduled_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "0000000000000000"
        )
        self.assertEqual(
            unchanged,
            (
                "3ff0000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "3ff0000000000000",
                "0000000000000000",
                "0000000000000000",
            ),
        )
        self.assertEqual(zero.second_segment.max_output_interval_width_numerator, "0")

    def test_source_is_exact_fail_closed_and_excludes_numeric_runtimes(self):
        source = (ROOT / "scheduled_reset.py").read_text(encoding="utf-8")
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
