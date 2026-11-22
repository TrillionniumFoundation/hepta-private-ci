"""Small exact controls for the frozen index537 continuation and tail check."""

from dataclasses import replace
import hashlib
import unittest

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile.checkpoint import (
    AuthenticCheckpoint,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    build_authentic_firststep_cursor,
    encode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
    build_initial_capsule,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    _row_action,
)

from .tail537 import (
    advance_to_index537,
    encode_raw_index537,
    first_tail_check,
)


ROWS = (((0, "bff0000000000000"), (1, "4000000000000000")), ())
VECTOR = ("3ff0000000000000", "bfd0000000000000")
DURATION = "4000000000000000"


def _index256_fixture():
    parent = build_authentic_firststep_cursor(
        build_initial_capsule("fixture", ROWS, [VECTOR], DURATION), 0
    )
    parent_payload = encode_authentic_firststep_cursor(parent)
    state = AuthenticCheckpoint(
        source_payload_sha256="1" * 64,
        parent_payload_sha256=hashlib.sha256(parent_payload).hexdigest(),
        lane=parent.lane,
        included_index=parent.included_index,
        iterate=parent.iterate,
        coefficient=parent.coefficient,
        growth_coefficient=parent.growth_coefficient,
        exponential_sum=parent.exponential_sum,
        partial=parent.partial,
    )
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    for next_index in range(2, 257):
        coefficient = state.coefficient * argument / next_index
        growth = state.growth_coefficient * tail_argument / next_index
        iterate = _row_action(state.iterate, parent.transition)
        state = replace(
            state,
            included_index=next_index,
            iterate=iterate,
            coefficient=coefficient,
            growth_coefficient=growth,
            exponential_sum=state.exponential_sum + coefficient,
            partial=tuple(
                left + coefficient * right
                for left, right in zip(state.partial, iterate, strict=True)
            ),
        )
    return state, parent_payload


class Tail537Tests(unittest.TestCase):
    def test_exact_fixture_reaches_index537_and_is_unique(self):
        state256, parent = _index256_fixture()
        state537 = advance_to_index537(state256, parent)
        result = first_tail_check(state537, parent)
        self.assertEqual(state537.included_index, 537)
        self.assertEqual(result["coordinate_count"], 2)
        self.assertEqual(result["unique_coordinate_count"], 2)
        self.assertTrue(result["all_coordinates_unique"])
        first = encode_raw_index537(state537)
        self.assertEqual(first, encode_raw_index537(state537))

    def test_wrong_boundary_is_rejected(self):
        state256, parent = _index256_fixture()
        with self.assertRaisesRegex(ValueError, "not index537"):
            first_tail_check(state256, parent)
        with self.assertRaisesRegex(ValueError, "not index537"):
            encode_raw_index537(state256)


if __name__ == "__main__":
    unittest.main()
