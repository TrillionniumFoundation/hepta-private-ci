"""Synthetic controls for detached authentic cursor validation."""

from fractions import Fraction
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
from qualification.hcsn_currentstate_n256_authentic_secondstep_cursor.cursor import (
    build_authentic_secondstep_cursor,
    encode_authentic_secondstep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    NonSubstochasticSignedIntervalError,
)

from .cursor import (
    detach_authentic_secondstep_cursor,
    decode_authentic_detached_cursor,
    encode_authentic_detached_cursor,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTOR = ("3ff0000000000000", "bfd0000000000000")
DURATION = "4000000000000000"


def source_payloads():
    capsule = build_initial_capsule("fixture", ROWS, [VECTOR], DURATION)
    parent = encode_authentic_firststep_cursor(
        build_authentic_firststep_cursor(capsule, 0)
    )
    source = encode_authentic_secondstep_cursor(
        build_authentic_secondstep_cursor(parent)
    )
    return parent, source


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class AuthenticDetachedCursorTest(unittest.TestCase):
    def test_detached_round_trip_preserves_exact_state_and_is_smaller(self):
        parent, source = source_payloads()
        detached = detach_authentic_secondstep_cursor(source)
        payload = encode_authentic_detached_cursor(detached)
        decoded = decode_authentic_detached_cursor(payload, parent)
        self.assertEqual(decoded, detached)
        self.assertEqual(encode_authentic_detached_cursor(decoded), payload)
        self.assertLess(len(payload), len(source))

    def test_wrong_external_parent_is_rejected(self):
        parent, source = source_payloads()
        payload = encode_authentic_detached_cursor(
            detach_authentic_secondstep_cursor(source)
        )
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "parent digest"
        ):
            decode_authentic_detached_cursor(payload, parent + b" ")

    def test_rehashed_state_drift_is_rejected_by_row_relation(self):
        parent, source = source_payloads()
        payload = encode_authentic_detached_cursor(
            detach_authentic_secondstep_cursor(source)
        )
        envelope = json.loads(payload)
        old = envelope["body"]["iterate"][0]
        shifted = Fraction(int(old[0]), int(old[1])) + 1
        envelope["body"]["iterate"][0] = [
            str(shifted.numerator),
            str(shifted.denominator),
        ]
        coefficient = Fraction(*map(int, envelope["body"]["coefficient"]))
        source_parent = json.loads(parent)["body"]
        parent_partial = Fraction(*map(int, source_parent["partial"][0]))
        replacement = parent_partial + coefficient * shifted
        envelope["body"]["partial"][0] = [
            str(replacement.numerator),
            str(replacement.denominator),
        ]
        envelope["body_sha256"] = hashlib.sha256(
            canonical(envelope["body"])
        ).hexdigest()
        tampered = canonical(envelope)
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "row-action relation"
        ):
            decode_authentic_detached_cursor(tampered, parent)


if __name__ == "__main__":
    unittest.main()
