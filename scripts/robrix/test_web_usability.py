"""Read actual focus/geometry receipts; unchanged screenshots cannot prove focus."""

import copy
import unittest
from web_usability import TAB_TARGETS, assess, focused, fully_visible


def state(name=None):
    return {
        "controls": {
            key: {
                "valid": True,
                "focused": key == name,
                "size": [50, 50],
                "clipped": [100, 100, 50, 50],
            }
            for key in TAB_TARGETS
        },
        "draft_matches_fixture": True,
    }


class TestActualUsabilityReceipt(unittest.TestCase):
    def test_stalled_or_skipped_focus_cannot_pass(self):
        trace = [state(name) for name in TAB_TARGETS]
        self.assertTrue(
            all(
                assess(
                    state("user_id_input"),
                    trace,
                    list(reversed(trace)),
                    state(),
                    trace,
                    True,
                ).values()
            )
        )
        stalled = [state("user_id_input")] * len(TAB_TARGETS)
        result = assess(state(), stalled, stalled, state(), stalled, True)
        self.assertFalse(result["initialTabStartsAtFirstInput"])
        self.assertFalse(result["forwardTabReachesAllControls"])
        self.assertFalse(result["reverseTabReachesAllControls"])
        self.assertIsNone(focused(state()))

    def test_clipped_controls_and_lost_draft_are_not_accepted(self):
        scrolled = state()
        self.assertTrue(fully_visible(scrolled["controls"]["signup_button"]))
        scrolled["controls"]["signup_button"]["clipped"][3] = 10
        lost = copy.deepcopy(scrolled)
        lost["draft_matches_fixture"] = False
        result = assess(state(), [], [], scrolled, [lost], False)
        self.assertFalse(result["wheelShowsAllLowerControls"])
        self.assertFalse(result["draftPreserved"])
        self.assertFalse(result["noSubmission"])

    def test_multiple_claimed_focus_owners_are_rejected(self):
        snapshot = state("user_id_input")
        snapshot["controls"]["password_input"]["focused"] = True
        with self.assertRaises(AssertionError):
            focused(snapshot)


if __name__ == "__main__":
    unittest.main()
