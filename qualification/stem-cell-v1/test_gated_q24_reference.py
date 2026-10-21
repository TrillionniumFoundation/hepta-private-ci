"""Differential golden tests for Rust CpuGatedHead Q24 arithmetic.

Fixtures assert exact math, not a true Rust or pretrained Encoder execution.
"""

import unittest

from gated_q24_reference import gated_head_digest, infer_gated_q24
from native_bridge import Q24


def head_with_gate(preactivation):
    return {
        "input_width": 1,
        "output_width": 1,
        "drive_weights_q24": [0],
        "prediction_weights_q24": [],
        "gate_weights_q24": [],
        "drive_bias_q24": [Q24],
        "prediction_bias_q24": [0],
        "gate_bias_q24": [preactivation],
    }


class GatedQ24ReferenceTests(unittest.TestCase):
    def test_hard_sigmoid_signed_half_ties_match_rust_goldens(self):
        for pre, expected in (
            (-Q24 - 1, 0),
            (-Q24, 0),
            (-3, Q24 // 2 - 2),
            (-1, Q24 // 2),
            (0, Q24 // 2),
            (1, Q24 // 2),
            (3, Q24 // 2 + 2),
            (Q24, Q24),
            (Q24 + 1, Q24),
        ):
            with self.subTest(pre=pre):
                self.assertEqual(
                    infer_gated_q24(head_with_gate(pre), [0]),
                    ((expected,), (0,)),
                )

    def test_two_rows_match_rust_cpu_head_golden(self):
        head = {
            "input_width": 2,
            "output_width": 2,
            "drive_weights_q24": [Q24, 0, 0, Q24],
            "prediction_weights_q24": [0, Q24, Q24, 0],
            "gate_weights_q24": [],
            "drive_bias_q24": [0, 0],
            "prediction_bias_q24": [0, 0],
            "gate_bias_q24": [-1, 3],
        }
        self.assertEqual(
            infer_gated_q24(head, [Q24 // 2, Q24 // 4]),
            ((Q24 // 4, Q24 // 8), (Q24 // 8, Q24 // 4 + 1)),
        )

    def test_compact_bank_digest_matches_frozen_rust_golden(self):
        head = {
            "input_width": 2,
            "output_width": 2,
            "drive_weights_q24": [Q24, 0, 0, Q24],
            "prediction_weights_q24": [],
            "gate_weights_q24": [],
            "drive_bias_q24": [0, 0],
            "prediction_bias_q24": [0, 0],
            "gate_bias_q24": [Q24, Q24],
        }
        self.assertEqual(
            gated_head_digest(head),
            "3b7962a1f859f4e3a2594c37a3d3b99e6c6c6813102947f9ab3e68aa0cb22e82",
        )

    def test_invalid_shapes_nonfinite_and_unsigned_coercions_rejected(self):
        invalid = [
            ("drive_weights_q24", []),
            ("gate_weights_q24", [0, 0]),
            ("prediction_bias_q24", []),
            ("drive_weights_q24", [True]),
            ("drive_weights_q24", [1.0]),
            ("drive_weights_q24", [9 * Q24]),
        ]
        for field, altered in invalid:
            with self.subTest(field=field, altered=altered):
                head = head_with_gate(0)
                head[field] = altered
                with self.assertRaises(ValueError):
                    infer_gated_q24(head, [0])
        for features in ([True], [1.0], [9 * Q24], [], [0, 0]):
            with self.subTest(features=features):
                with self.assertRaises(ValueError):
                    infer_gated_q24(head_with_gate(0), features)
        with self.assertRaises(ValueError):
            infer_gated_q24({**head_with_gate(0), "production_authorized": True}, [0])

    def test_dense_explicit_zero_gate_is_valid_and_digest_distinct(self):
        # A 1x1 explicit zero gate matrix has exactly one coefficient, and
        # must remain a legitimate dense form. Only the empty tuple/list is
        # the compact constant-zero representation. Digest binds physical
        # coefficient layout even when both choices produce the same outputs.
        compact = head_with_gate(0)
        dense = head_with_gate(0)
        dense["gate_weights_q24"] = [0]
        self.assertEqual(
            infer_gated_q24(dense, [Q24]),
            infer_gated_q24(compact, [Q24]),
        )
        self.assertNotEqual(gated_head_digest(dense), gated_head_digest(compact))
        with self.assertRaises(ValueError):
            infer_gated_q24({**compact, "gate_weights_q24": [0, 0]}, [0])

    def test_bounded_output_overflow_fails_closed(self):
        head = {
            "input_width": 2,
            "output_width": 1,
            "drive_weights_q24": [8 * Q24, 8 * Q24],
            "prediction_weights_q24": [],
            "gate_weights_q24": [],
            "drive_bias_q24": [0],
            "prediction_bias_q24": [0],
            "gate_bias_q24": [Q24],
        }
        with self.assertRaises(ValueError):
            infer_gated_q24(head, [8 * Q24, 8 * Q24])

    def test_reference_is_pure_and_never_mutates_weights(self):
        head = head_with_gate(-1)
        before = {
            key: value.copy() if isinstance(value, list) else value
            for key, value in head.items()
        }
        self.assertEqual(infer_gated_q24(head, [0]), ((Q24 // 2,), (0,)))
        self.assertEqual(head, before)


if __name__ == "__main__":
    unittest.main()
