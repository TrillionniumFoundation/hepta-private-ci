import ast
import struct
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from qualification.hcsn_currentstate_second_feedback_interval.second_feedback import (
    second_feedback_outputs_from_fp64_amplitude,
)


ROOT = Path(__file__).parent


def _hex(value):
    return struct.pack(">d", value).hex()


class SecondFeedbackIntervalTest(unittest.TestCase):
    def test_second_feedback_matches_independent_closed_form(self):
        outputs, certificate = second_feedback_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        with localcontext() as context:
            context.prec = 100
            one = Decimal(1)
            two = Decimal(2)
            three = Decimal(3)
            delay = Decimal("0.25")
            decay = Decimal("-0.75").exp()
            occupation_zero = (one - decay) / three
            first_moment = (one - decay * (one + three * delay)) / 9
            second_moment = (
                two - decay * (two + 6 * delay + 9 * delay * delay)
            ) / 27
            occupation_one = decay * occupation_zero + two * first_moment
            active_one_end = decay * (decay + two * delay)
            occupation_two = (
                active_one_end * occupation_zero
                + two * decay * first_moment
                + two * second_moment
            )
            total_occupation = occupation_zero + occupation_one + occupation_two
            active_two_end = decay * (
                decay * decay
                + 4 * decay * delay
                + two * delay * delay
            )
            expected = (
                _hex(float(active_two_end)),
                _hex(float(active_one_end)),
                _hex(float(decay)),
                _hex(float(total_occupation)),
                _hex(float(two * total_occupation)),
                _hex(float(total_occupation)),
                _hex(float(two * (occupation_zero + occupation_one))),
                _hex(float(two * occupation_two)),
            )
        self.assertEqual(outputs, expected)
        self.assertTrue(certificate.same_ctmc_hit_flux_encoded)
        self.assertTrue(certificate.two_deterministic_delay_releases_encoded)
        self.assertTrue(certificate.third_segment_second_feedback_encoded)
        self.assertTrue(certificate.nonreturning_upper_preserved)
        self.assertFalse(certificate.fourth_or_later_segment_encoded)
        self.assertFalse(certificate.arbitrary_history_encoded)
        self.assertFalse(certificate.authentic_n256_bundle_loaded)
        self.assertFalse(certificate.current_state_provider_qualified)

    def test_signed_mirror_and_zero_delay_are_exact(self):
        positive, positive_certificate = second_feedback_outputs_from_fp64_amplitude(
            "3ff0000000000000", "3fd0000000000000"
        )
        negative, negative_certificate = second_feedback_outputs_from_fp64_amplitude(
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
            positive_certificate.third_segment.highest_included_poisson_index,
            negative_certificate.third_segment.highest_included_poisson_index,
        )
        unchanged, zero = second_feedback_outputs_from_fp64_amplitude(
            "3ff0000000000000", "0000000000000000"
        )
        self.assertEqual(
            unchanged,
            (
                "3ff0000000000000",
                "3ff0000000000000",
                "3ff0000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
                "0000000000000000",
            ),
        )
        self.assertEqual(zero.third_segment.outputs[7].upper_numerator, "0")

    def test_source_is_exact_fail_closed_and_excludes_numeric_runtimes(self):
        source = (ROOT / "second_feedback.py").read_text(encoding="utf-8")
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
