import ast
import struct
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from qualification.hcsn_currentstate_hit_delay_reset_interval.hit_delay_reset import (
    hit_delay_reset_outputs_from_fp64_amplitude,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class HitDelayResetIntervalTest(unittest.TestCase):
    def test_actual_hit_flux_returns_after_one_deterministic_delay(self):
        outputs, certificate = hit_delay_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        with localcontext() as context:
            context.prec = 100
            one = Decimal(1)
            delay = Decimal("0.25")
            decay = Decimal("-0.75").exp()
            first_occupation = (one - decay) / 3
            tau_integral = (one - decay * (one + 3 * delay)) / 9
            second_occupation = decay * (one - decay) / 3 + 2 * tau_integral
            active = decay * (decay + 2 * delay)
            returned = 2 * first_occupation
            pending = 2 * second_occupation
            expected = (
                _hex(float(active)),
                _hex(float(decay)),
                _hex(float(first_occupation + second_occupation)),
                _hex(float(2 * first_occupation + 2 * second_occupation)),
                _hex(float(first_occupation + second_occupation)),
                _hex(float(returned)),
                _hex(float(pending)),
            )
        self.assertEqual(outputs, expected)
        self.assertTrue(certificate.same_ctmc_hit_flux_encoded)
        self.assertTrue(certificate.one_deterministic_delay_release_encoded)
        self.assertTrue(certificate.first_feedback_segment_encoded)
        self.assertTrue(certificate.nonreturning_upper_preserved)
        self.assertFalse(certificate.third_or_later_cycle_encoded)
        self.assertFalse(certificate.arbitrary_history_encoded)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.current_state_provider_qualified)

    def test_signed_mirror_and_zero_delay_are_exact(self):
        positive, positive_certificate = hit_delay_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        negative, negative_certificate = hit_delay_reset_outputs_from_fp64_amplitude(
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
        unchanged, zero = hit_delay_reset_outputs_from_fp64_amplitude(
            "3ff0000000000000", "0000000000000000"
        )
        self.assertEqual(
            unchanged,
            (
                "3ff0000000000000",
                "3ff0000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
            ),
        )
        self.assertEqual(zero.pending_interval.upper_numerator, "0")

    def test_source_is_exact_fail_closed_and_excludes_numeric_runtimes(self):
        source = (ROOT / "hit_delay_reset.py").read_text(encoding="utf-8")
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
