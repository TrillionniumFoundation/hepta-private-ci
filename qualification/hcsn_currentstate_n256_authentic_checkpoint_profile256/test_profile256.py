"""Synthetic controls for exact checkpoint extension to index 256."""

import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    advance_checkpoint,
    encode_checkpoint,
    start_from_index_two,
)
from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile128.extended import (
    advance_extended_checkpoint,
    encode_extended_checkpoint,
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

from .profile256 import (
    advance_to_index256,
    decode_index256,
    encode_index256,
    start_from_index128,
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
    index32_state = advance_checkpoint(
        start_from_index_two(source, parent), parent, 32
    )
    index32 = encode_checkpoint(index32_state)
    index128 = encode_extended_checkpoint(
        advance_extended_checkpoint(
            advance_extended_checkpoint(index32_state, parent, 64),
            parent,
            128,
        )
    )
    return parent, source, index32, index128


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class AuthenticIndex256CheckpointTest(unittest.TestCase):
    def test_warm_and_cold_index256_are_byte_exact(self):
        parent, source, index32, index128 = inputs()
        current = start_from_index128(index128, index32, source, parent)
        payload = encode_index256(advance_to_index256(current, parent))
        cold = decode_index256(payload, index128, index32, source, parent)
        self.assertEqual(encode_index256(cold), payload)

    def test_wrong_index128_source_is_rejected(self):
        parent, source, index32, index128 = inputs()
        current = start_from_index128(index128, index32, source, parent)
        payload = encode_index256(advance_to_index256(current, parent))
        with self.assertRaises(NonSubstochasticSignedIntervalError):
            decode_index256(
                payload, index128 + b" ", index32, source, parent
            )

    def test_rehashed_state_drift_is_rejected(self):
        parent, source, index32, index128 = inputs()
        current = start_from_index128(index128, index32, source, parent)
        envelope = json.loads(
            encode_index256(advance_to_index256(current, parent))
        )
        envelope["body"]["included_index"] = 255
        envelope["body_sha256"] = hashlib.sha256(
            canonical(envelope["body"])
        ).hexdigest()
        with self.assertRaisesRegex(
            NonSubstochasticSignedIntervalError, "binding mismatch"
        ):
            decode_index256(
                canonical(envelope), index128, index32, source, parent
            )


if __name__ == "__main__":
    unittest.main()
