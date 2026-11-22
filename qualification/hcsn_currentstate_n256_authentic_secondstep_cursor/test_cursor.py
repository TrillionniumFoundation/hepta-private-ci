"""Synthetic controls for the authentic second-step cursor."""

import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    build_authentic_firststep_cursor,
    encode_authentic_firststep_cursor,
)
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
    build_authentic_secondstep_cursor,
    decode_authentic_secondstep_cursor,
    encode_authentic_secondstep_cursor,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTOR = ("3ff0000000000000", "bfd0000000000000")
DURATION = "4000000000000000"


def parent_payload():
    capsule = build_initial_capsule("fixture", ROWS, [VECTOR], DURATION)
    return encode_authentic_firststep_cursor(
        build_authentic_firststep_cursor(capsule, 0)
    )


class AuthenticSecondStepCursorTest(unittest.TestCase):
    def test_matches_existing_exact_cursor_after_two_actions(self):
        candidate = build_authentic_secondstep_cursor(parent_payload())
        reference = start_signed_recurrence_cursor(ROWS, VECTOR, DURATION)
        reference, result = advance_signed_recurrence_cursor(reference, tail_checks=2)
        self.assertIsNone(result)
        self.assertEqual(candidate.included_index, reference.included_index)
        self.assertEqual(candidate.iterate, reference.iterate)
        self.assertEqual(candidate.coefficient, reference.coefficient)
        self.assertEqual(candidate.growth_coefficient, reference.growth_coefficient)
        self.assertEqual(candidate.exponential_sum, reference.exponential_sum)
        self.assertEqual(candidate.partial, reference.partial)

    def test_parent_is_embedded_and_cold_round_trip_is_exact(self):
        original = parent_payload()
        payload = encode_authentic_secondstep_cursor(
            build_authentic_secondstep_cursor(original)
        )
        decoded = decode_authentic_secondstep_cursor(payload)
        self.assertEqual(decoded.parent_payload, original)
        self.assertEqual(encode_authentic_secondstep_cursor(decoded), payload)
        self.assertLessEqual(len(payload), MAX_CURSOR_BYTES)

        envelope = json.loads(payload)
        envelope["body"]["included_index"] = 3
        tampered = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "digest"):
            decode_authentic_secondstep_cursor(tampered)

    def test_embedded_parent_corruption_is_rejected(self):
        payload = encode_authentic_secondstep_cursor(
            build_authentic_secondstep_cursor(parent_payload())
        )
        envelope = json.loads(payload)
        envelope["body"]["parent_payload_sha256"] = "0" * 64
        body_bytes = json.dumps(
            envelope["body"], sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        envelope["body_sha256"] = hashlib.sha256(body_bytes).hexdigest()
        tampered = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "parent digest"):
            decode_authentic_secondstep_cursor(tampered)


if __name__ == "__main__":
    unittest.main()
