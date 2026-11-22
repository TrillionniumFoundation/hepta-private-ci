"""Synthetic controls for fixed-boundary exact checkpoint replay."""

from fractions import Fraction
import hashlib
import json
import unittest

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
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (  # noqa: E501
    NonSubstochasticSignedIntervalError,
)

from .checkpoint import (
    advance_checkpoint,
    decode_checkpoint,
    encode_checkpoint,
    start_from_index_two,
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
    detached = encode_authentic_detached_cursor(
        detach_authentic_secondstep_cursor(second)
    )
    return parent, detached


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class AuthenticCheckpointTest(unittest.TestCase):
    def test_warm_and_cold_fixed_boundaries_are_byte_exact(self):
        parent, source = inputs()
        current = start_from_index_two(source, parent)
        for boundary in (4, 8):
            current = advance_checkpoint(current, parent, boundary)
            payload = encode_checkpoint(current)
            cold = decode_checkpoint(payload, source, parent)
            self.assertEqual(encode_checkpoint(cold), payload)

    def test_wrong_source_is_rejected(self):
        parent, source = inputs()
        state = advance_checkpoint(start_from_index_two(source, parent), parent, 4)
        payload = encode_checkpoint(state)
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "binding"
        ):
            decode_checkpoint(payload, source + b" ", parent)

    def test_rehashed_state_drift_is_rejected_by_replay(self):
        parent, source = inputs()
        state = advance_checkpoint(start_from_index_two(source, parent), parent, 4)
        payload = encode_checkpoint(state)
        envelope = json.loads(payload)
        old = envelope["body"]["iterate"][0]
        shifted = Fraction(int(old[0]), int(old[1])) + 1
        envelope["body"]["iterate"][0] = [
            str(shifted.numerator),
            str(shifted.denominator),
        ]
        envelope["body_sha256"] = hashlib.sha256(
            canonical(envelope["body"])
        ).hexdigest()
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "replay mismatch"
        ):
            decode_checkpoint(canonical(envelope), source, parent)


if __name__ == "__main__":
    unittest.main()
