"""Synthetic controls for the authentic-domain first-step cursor."""

import json
import unittest

from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
    build_initial_capsule,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
)
from qualification.hcsn_currentstate_n256_signed_recurrence_cursor.cursor import (
    advance_signed_recurrence_cursor,
    start_signed_recurrence_cursor,
)

from .cursor import (
    MAX_CURSOR_BYTES,
    build_authentic_firststep_cursor,
    decode_authentic_firststep_cursor,
    encode_authentic_firststep_cursor,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTOR = ("3ff0000000000000", "bfd0000000000000")
DURATION = "4000000000000000"


class AuthenticFirstStepCursorTest(unittest.TestCase):
    def test_matches_existing_exact_cursor_after_one_action(self):
        capsule = build_initial_capsule("fixture", ROWS, [VECTOR], DURATION)
        candidate = build_authentic_firststep_cursor(capsule, 0)
        reference, result = advance_signed_recurrence_cursor(
            start_signed_recurrence_cursor(ROWS, VECTOR, DURATION), tail_checks=1
        )
        self.assertIsNone(result)
        self.assertEqual(candidate.included_index, reference.included_index)
        self.assertEqual(candidate.iterate, reference.iterate)
        self.assertEqual(candidate.coefficient, reference.coefficient)
        self.assertEqual(candidate.growth_coefficient, reference.growth_coefficient)
        self.assertEqual(candidate.exponential_sum, reference.exponential_sum)
        self.assertEqual(candidate.partial, reference.partial)

    def test_canonical_cold_round_trip_without_another_action(self):
        capsule = build_initial_capsule("fixture", ROWS, [VECTOR], DURATION)
        payload = encode_authentic_firststep_cursor(
            build_authentic_firststep_cursor(capsule, 0)
        )
        decoded = decode_authentic_firststep_cursor(payload)
        self.assertEqual(encode_authentic_firststep_cursor(decoded), payload)
        self.assertLessEqual(len(payload), MAX_CURSOR_BYTES)

        envelope = json.loads(payload)
        envelope["body"]["included_index"] = 2
        tampered = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "digest"):
            decode_authentic_firststep_cursor(tampered)
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "noncanonical"):
            decode_authentic_firststep_cursor(payload + b" ")

    def test_fail_closed_when_index_zero_nonuniqueness_is_not_proven(self):
        capsule = build_initial_capsule(
            "fixture", ROWS, [VECTOR], "3e112e0be826d695"
        )
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "not proven non-unique"
        ):
            build_authentic_firststep_cursor(capsule, 0)
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "vector index"):
            build_authentic_firststep_cursor(
                build_initial_capsule("fixture", ROWS, [VECTOR], DURATION), 1
            )


if __name__ == "__main__":
    unittest.main()
