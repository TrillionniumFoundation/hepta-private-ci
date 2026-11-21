"""Synthetic tests for the authentic-domain initial capsule serializer."""

import json
import unittest

from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
)

from .capsule import (
    MAX_CAPSULE_BYTES,
    build_initial_capsule,
    decode_initial_capsule,
    encode_initial_capsule,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTORS = (("3ff0000000000000", "bfd0000000000000"),)
DURATION = "3f50624dd2f1a9fc"


class InitialCapsuleTest(unittest.TestCase):
    def test_round_trip_reconstructs_initial_state_exactly(self):
        original = build_initial_capsule("fixture", ROWS, VECTORS, DURATION)
        payload = encode_initial_capsule(original)
        decoded = decode_initial_capsule(payload)
        self.assertEqual(encode_initial_capsule(decoded), payload)
        self.assertEqual(decoded, original)
        self.assertLessEqual(len(payload), MAX_CAPSULE_BYTES)

    def test_snapshot_and_corruption_controls(self):
        rows = [[list(entry) for entry in row] for row in ROWS]
        vectors = [list(VECTORS[0])]
        capsule = build_initial_capsule("fixture", rows, vectors, DURATION)
        rows[0][0][1] = "7ff0000000000000"
        vectors[0][0] = "7ff0000000000000"
        payload = encode_initial_capsule(capsule)
        envelope = json.loads(payload)
        envelope["body"]["duration_hex"] = "0000000000000000"
        tampered = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "digest"):
            decode_initial_capsule(tampered)
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "noncanonical"):
            decode_initial_capsule(payload + b" ")

    def test_hard_bounds(self):
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "vector count"):
            build_initial_capsule("fixture", ROWS, (), DURATION)
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "dimension"):
            build_initial_capsule("fixture", ROWS, (("0",),), DURATION)
        with self.assertRaisesRegex(NonSubstochasticSignedIntervalError, "invalid lane"):
            build_initial_capsule("other", ROWS, VECTORS, DURATION)


if __name__ == "__main__":
    unittest.main()
