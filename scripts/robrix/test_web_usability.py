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


class ThemeSwitchGate(unittest.TestCase):
    def test_owner_or_focus_loss_cannot_pass(self):
        import copy
        from chat_usability import switch_checks

        before = {
            "controls": {"composer": {"uid": "editor-1", "focused": True}},
            "selected_room": "!fixture:example.invalid",
            "selected_tab": "Home",
            "fixture_logged_in": True,
            "console_authority": [False, False, False, 0, False],
        }
        after = dict(
            copy.deepcopy(before), theme="PolarPrism", draft_matches_fixture=True
        )
        good = switch_checks(before, after, "PolarPrism")
        self.assertTrue(all(value for key, value in good.items() if key != "theme"))
        for key, replacement in [
            ("selected_room", None),
            ("selected_tab", "Console"),
            ("fixture_logged_in", False),
            ("console_authority", [True]),
            ("draft_matches_fixture", False),
            ("theme", "ObsidianCeramic"),
        ]:
            changed = dict(copy.deepcopy(after), **{key: replacement})
            self.assertFalse(
                all(
                    value
                    for key, value in switch_checks(
                        before, changed, "PolarPrism"
                    ).items()
                    if key != "theme"
                )
            )
        for key, value in [("uid", "replacement-editor"), ("focused", False)]:
            changed = copy.deepcopy(after)
            changed["controls"]["composer"][key] = value
            self.assertFalse(
                all(
                    value
                    for key, value in switch_checks(
                        before, changed, "PolarPrism"
                    ).items()
                    if key != "theme"
                )
            )

    def test_keyboard_activation_keeps_theme_control_focus(self):
        from chat_usability import switch_checks

        state = {
            "controls": {
                "composer": {"uid": "same", "focused": False},
                "theme_a": {"focused": True},
            },
            "theme": "DeepSpaceTitanium",
            "draft_matches_fixture": True,
            "selected_room": "synthetic",
            "selected_tab": "Home",
            "fixture_logged_in": True,
            "console_authority": [False],
        }
        check = switch_checks(
            state, state, "DeepSpaceTitanium", expected_focus="theme_a"
        )
        self.assertTrue(all(v for k, v in check.items() if k != "theme"))
        self.assertFalse(
            switch_checks(state, state, "DeepSpaceTitanium")["input_mode_focus"]
        )


class AdaptiveHandoffGate(unittest.TestCase):
    def test_destination_draft_and_authority_drift_fail(self):
        from chat_usability import adaptive_checks

        sample = {
            "selected_room": "synthetic",
            "displayed_room": "synthetic",
            "draft_matches_fixture": True,
            "desktop": True,
            "stack_transitioning": False,
            "dock_selection_matches_room": True,
            "controls": {"composer": {"valid": True}},
            "send_context_unset": True,
            "fixture_logged_in": True,
            "console_authority": [False, False, False, 0, False],
        }
        self.assertTrue(
            all(
                adaptive_checks(
                    sample, "synthetic", "draft_matches_fixture", True
                ).values()
            )
        )
        for key, value in [
            ("selected_room", "old"),
            ("displayed_room", "old"),
            ("draft_matches_fixture", False),
            ("desktop", False),
            ("stack_transitioning", True),
            ("dock_selection_matches_room", False),
            ("send_context_unset", False),
            ("fixture_logged_in", False),
            ("console_authority", [True]),
        ]:
            bad = dict(sample, **{key: value})
            self.assertFalse(
                all(
                    adaptive_checks(
                        bad, "synthetic", "draft_matches_fixture", True
                    ).values()
                ),
                key,
            )


class RoomPreviewGeometryGate(unittest.TestCase):
    def test_missing_short_or_clipped_snippets_fail(self):
        from chat_usability import previews_readable

        good = [{"visible": True, "height": 34, "clipped_height": 34} for _ in range(6)]
        self.assertTrue(previews_readable(good))
        self.assertFalse(previews_readable(good[:5]))
        for change in ({"visible": False}, {"height": 4}, {"clipped_height": 4}):
            bad = copy.deepcopy(good)
            bad[0].update(change)
            self.assertFalse(previews_readable(bad))
