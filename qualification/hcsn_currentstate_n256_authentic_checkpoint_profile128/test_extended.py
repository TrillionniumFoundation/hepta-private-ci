"""Synthetic controls for exact checkpoint extension from index 32."""

from fractions import Fraction
import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    advance_checkpoint,
    encode_checkpoint,
    start_from_index_two,
)
from qualification.hcsn_currentstate_n256_authentic_detached_cursor.cursor import (
    detach_authentic_secondstep_cursor,
    encode_authentic_detached_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    build_authentic_firststep_cursor,
    encode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
    build_initial_capsule,
)
from qualification.hcsn_currentstate_n256_authentic_secondstep_cursor.cursor import (
    build_authentic_secondstep_cursor,
    encode_authentic_secondstep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
)

from .extended import (
    _fraction_from_pair,
    _fraction_pair,
    advance_extended_checkpoint,
    decode_extended_checkpoint,
    encode_extended_checkpoint,
    start_from_index32,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTOR = ("3ff0000000000000", "bfd0000000000000")
DURATION = "4000000000000000"


def inputs():
    capsule = build_initial_capsule("fixture", ROWS, [VECTOR], DURATION)
    parent = encode_authentic_firststep_cursor(
        build_authentic_firststep_cursor(capsule, 0)
    )
    second = encode_authentic_secondstep_cursor(
        build_authentic_secondstep_cursor(parent)
    )
    source = encode_authentic_detached_cursor(
        detach_authentic_secondstep_cursor(second)
    )
    index32 = encode_checkpoint(
        advance_checkpoint(start_from_index_two(source, parent), parent, 32)
    )
    return parent, source, index32


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class AuthenticExtendedCheckpointTest(unittest.TestCase):
    def test_large_fraction_uses_hex_without_disabling_decimal_safety(self):
        value = Fraction((1 << 18_000) + 17, (1 << 7_000) + 3)
        pair = _fraction_pair(value)
        self.assertEqual(_fraction_from_pair(pair, "large"), value)
        self.assertGreater(len(pair[0]), 4_300)

    def test_noncanonical_hex_is_rejected(self):
        for pair in (["00", "1"], ["A", "1"], ["-0", "1"], ["+1", "1"]):
            with self.subTest(pair=pair):
                with self.assertRaises(NonSubstochasticSignedIntervalError):
                    _fraction_from_pair(pair, "synthetic")

    def test_warm_and_cold_extended_boundaries_are_byte_exact(self):
        parent, source, index32 = inputs()
        current = start_from_index32(index32, source, parent)
        for boundary in (64, 128):
            current = advance_extended_checkpoint(current, parent, boundary)
            payload = encode_extended_checkpoint(current)
            cold = decode_extended_checkpoint(
                payload, index32, source, parent
            )
            self.assertEqual(encode_extended_checkpoint(cold), payload)

    def test_wrong_index32_source_is_rejected(self):
        parent, source, index32 = inputs()
        current = advance_extended_checkpoint(
            start_from_index32(index32, source, parent), parent, 64
        )
        payload = encode_extended_checkpoint(current)
        with self.assertRaises(NonSubstochasticSignedIntervalError):
            decode_extended_checkpoint(
                payload, index32 + b" ", source, parent
            )

    def test_rehashed_state_drift_is_rejected_by_replay(self):
        parent, source, index32 = inputs()
        current = advance_extended_checkpoint(
            start_from_index32(index32, source, parent), parent, 64
        )
        envelope = json.loads(encode_extended_checkpoint(current))
        old = envelope["body"]["iterate"][0]
        shifted = Fraction(int(old[0], 16), int(old[1], 16)) + 1
        envelope["body"]["iterate"][0] = _fraction_pair(shifted)
        envelope["body_sha256"] = hashlib.sha256(
            canonical(envelope["body"])
        ).hexdigest()
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "replay mismatch"
        ):
            decode_extended_checkpoint(
                canonical(envelope), index32, source, parent
            )


if __name__ == "__main__":
    unittest.main()
