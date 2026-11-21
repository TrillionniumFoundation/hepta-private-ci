"""Small-fixture tests for the exact signed recurrence cursor."""

import json
import unittest

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
    non_substochastic_signed_outputs_from_fp64_intervals,
)

from .cursor import (
    MAX_CURSOR_BYTES,
    MAX_DIMENSION,
    advance_signed_recurrence_cursor,
    decode_signed_recurrence_cursor,
    encode_signed_recurrence_cursor,
    start_signed_recurrence_cursor,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTORS = (
    ("3ff0000000000000", "bfd0000000000000"),
    ("bff0000000000000", "3fd0000000000000"),
)
DURATION = "3fe0000000000000"


def finish(cursor, *, cold_every_step):
    payloads = []
    while cursor is not None:
        cursor, result = advance_signed_recurrence_cursor(cursor, tail_checks=1)
        if result is not None:
            return result, tuple(payloads)
        if cold_every_step:
            payload = encode_signed_recurrence_cursor(cursor)
            payloads.append(payload)
            cursor = decode_signed_recurrence_cursor(payload)
    raise AssertionError("cursor finished without a result")


class SignedRecurrenceCursorTest(unittest.TestCase):
    def test_continuous_and_every_step_cold_resume_equal_scalar_exactly(self):
        for vector in VECTORS:
            expected = non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, vector, DURATION
            )
            continuous, no_payloads = finish(
                start_signed_recurrence_cursor(ROWS, vector, DURATION),
                cold_every_step=False,
            )
            resumed, payloads = finish(
                start_signed_recurrence_cursor(ROWS, vector, DURATION),
                cold_every_step=True,
            )
            self.assertEqual(no_payloads, ())
            self.assertEqual(continuous, expected)
            self.assertEqual(resumed, expected)
            self.assertTrue(payloads)
            self.assertTrue(all(len(payload) <= MAX_CURSOR_BYTES for payload in payloads))

    def test_snapshot_and_zero_duration(self):
        mutable_rows = [[list(entry) for entry in row] for row in ROWS]
        mutable_vector = list(VECTORS[0])
        cursor = start_signed_recurrence_cursor(
            mutable_rows, mutable_vector, "0000000000000000"
        )
        mutable_rows[0][0][1] = "7ff0000000000000"
        mutable_vector[0] = "7ff0000000000000"
        cursor, result = advance_signed_recurrence_cursor(cursor, tail_checks=1)
        self.assertIsNone(cursor)
        self.assertEqual(
            result,
            non_substochastic_signed_outputs_from_fp64_intervals(
                ROWS, VECTORS[0], "0000000000000000"
            ),
        )

    def test_canonical_digest_and_corruption_controls(self):
        cursor = start_signed_recurrence_cursor(ROWS, VECTORS[0], DURATION)
        cursor, result = advance_signed_recurrence_cursor(cursor, tail_checks=1)
        self.assertIsNone(result)
        payload = encode_signed_recurrence_cursor(cursor)
        self.assertEqual(
            encode_signed_recurrence_cursor(
                decode_signed_recurrence_cursor(payload)
            ),
            payload,
        )

        envelope = json.loads(payload)
        envelope["body"]["included_index"] += 1
        tampered = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "digest or schema"
        ):
            decode_signed_recurrence_cursor(tampered)
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "noncanonical"
        ):
            decode_signed_recurrence_cursor(payload + b" ")
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "invalid cursor payload"
        ):
            decode_signed_recurrence_cursor(b"0" * (MAX_CURSOR_BYTES + 1))

    def test_hard_limits_and_fail_closed_term_budget(self):
        large_rows = tuple(() for _ in range(MAX_DIMENSION + 1))
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "dimension outside"
        ):
            start_signed_recurrence_cursor(
                large_rows,
                ("0000000000000000",) * len(large_rows),
                DURATION,
            )
        cursor = start_signed_recurrence_cursor(
            ROWS, VECTORS[0], DURATION, max_terms=1
        )
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "max_terms"):
            advance_signed_recurrence_cursor(cursor, tail_checks=1)
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "tail_checks"
        ):
            advance_signed_recurrence_cursor(cursor, tail_checks=0)


if __name__ == "__main__":
    unittest.main()
