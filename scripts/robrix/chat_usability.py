"""Real canvas theme clicks with read-only synthetic Rust state observation."""

import json
import time

MARKER = "[hepta-chat-observation] "


def snapshots(messages):
    return [
        json.loads(message.split(MARKER, 1)[1])
        for message in messages
        if MARKER in message
    ]


def switch_checks(before, after, theme, expected_focus="composer"):
    return {
        "theme": theme,
        "selected": after["theme"] == theme,
        "draft": after["draft_matches_fixture"],
        "editor_identity": after["controls"]["composer"]["uid"]
        == before["controls"]["composer"]["uid"],
        "input_mode_focus": after["controls"][expected_focus]["focused"],
        "room": after["selected_room"] == before["selected_room"],
        "tab": after["selected_tab"] == before["selected_tab"],
        "account_fixture": after["fixture_logged_in"] == before["fixture_logged_in"],
        "console_authority": after["console_authority"] == before["console_authority"],
    }


def capture_theme_switches(page, messages, out):
    def latest(after=0):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            samples = snapshots(messages)
            if samples and samples[-1]["sequence"] > after:
                return samples[-1]
            page.wait_for_timeout(50)
        raise AssertionError("No fresh real Rust chat observation")

    def click(snapshot, name):
        x, y, w, h = snapshot["controls"][name]["clipped"]
        assert w > 8 and h > 8, f"Actual {name} geometry is empty"
        page.mouse.click(x + w / 2, y + h / 2)

    initial = latest()
    header = initial["controls"]["header"]["clipped"]
    timeline = initial["controls"]["timeline"]["clipped"]
    composer = initial["controls"]["composer"]["clipped"]
    assert header[3] >= 76 and composer[3] >= 66, (
        "Header/composer lost their reserved geometry"
    )
    assert timeline[1] >= header[1] + header[3] - 1, "Timeline overlaps room header"
    click(initial, "composer")
    page.keyboard.type("theme-draft-fixture")
    page.wait_for_timeout(200)
    before = latest(initial["sequence"])
    assert before["draft_matches_fixture"] and before["controls"]["composer"]["focused"]
    checks = []
    try:
        for button, theme in [
            ("theme_a", "DeepSpaceTitanium"),
            ("theme_b", "PolarPrism"),
            ("theme_c", "ObsidianCeramic"),
        ]:
            click(before, button)
            page.wait_for_timeout(250)
            after = latest(before["sequence"])
            check = switch_checks(before, after, theme)
            checks.append(check)
            page.screenshot(path=str(out / f"web-theme-switch-{theme}.png"))
            assert all(v for k, v in check.items() if k != "theme"), check
            before = after
        # Tab traversal is real; only activate after observation proves the
        # theme button owns focus. Never send activation to an unknown control.
        for _ in range(32):
            page.keyboard.press("Tab")
            page.wait_for_timeout(100)
            candidate = latest(before["sequence"])
            before = candidate
            if candidate["controls"]["theme_a"]["focused"]:
                break
        assert before["controls"]["theme_a"]["focused"], (
            "Theme selector was not keyboard reachable"
        )
        page.keyboard.press("Space")
        page.wait_for_timeout(250)
        after = latest(before["sequence"])
        check = switch_checks(
            before, after, "DeepSpaceTitanium", expected_focus="theme_a"
        )
        check["activation"] = "keyboard"
        checks.append(check)
        page.screenshot(path=str(out / "web-theme-switch-keyboard.png"))
        assert all(v for k, v in check.items() if k not in ("theme", "activation")), (
            check
        )
    finally:
        (out / "web-theme-switches.json").write_text(
            json.dumps(
                {
                    "fixture": True,
                    "liveAccounts": False,
                    "submissionKeysSent": False,
                    "checks": checks,
                    "activeSdkReplyEditQualified": False,
                },
                indent=2,
            )
        )


def adaptive_checks(sample, room, draft, desktop):
    """A new adaptive editor may own the state; the destination may not drift."""
    return {
        "selected_room": sample["selected_room"] == room,
        "displayed_room": sample["displayed_room"] == room,
        "draft": sample[draft],
        "actual_mode": sample["desktop"] is desktop,
        "settled": not sample["stack_transitioning"],
        "dock_destination": not desktop or sample["dock_selection_matches_room"],
        "real_editor": sample["controls"]["composer"]["valid"],
        "no_send_context": sample["send_context_unset"],
        "fixture_account": sample["fixture_logged_in"],
        "console_unconfigured": sample["console_authority"]
        == [False, False, False, 0, False],
    }


def capture_adaptive_handoff(page, messages, out):
    """Continuous real resize/navigation, using only fixed synthetic drafts."""
    design = "!hepta-fixture-0:example.invalid"
    research = "!hepta-fixture-1:example.invalid"
    trace = []

    def settle(label, predicate):
        previous = snapshots(messages)[-1]["sequence"]
        deadline = time.monotonic() + 8
        sample = None
        while time.monotonic() < deadline:
            samples = snapshots(messages)
            if samples and samples[-1]["sequence"] > previous:
                sample = samples[-1]
                if predicate(sample):
                    break
            page.wait_for_timeout(50)
        trace.append({"step": label, "sample": sample})
        page.screenshot(path=str(out / f"web-adaptive-{label}.png"))
        assert sample is not None and predicate(sample), trace[-1]
        return sample

    def chat(label, room, draft, desktop):
        return settle(
            label,
            lambda sample: all(adaptive_checks(sample, room, draft, desktop).values()),
        )

    def click(sample, name):
        control = sample["controls"][name]
        x, y, w, h = control["clipped"]
        assert control["valid"] and w > 8 and h > 8, (name, control)
        page.mouse.click(x + w / 2, y + h / 2)

    try:
        initial = chat("wide-design", design, "draft_matches_fixture", True)
        page.set_viewport_size({"width": 520, "height": 760})
        compact = chat("compact-design", design, "draft_matches_fixture", False)
        click(compact, "back")
        listing = settle(
            "room-list",
            lambda s: (
                s["selected_room"] is None
                and not s["stack_transitioning"]
                and s["controls"]["rooms_list"]["valid"]
            ),
        )
        # The six-row synthetic list has deterministic real row geometry.
        # This is a pointer event, not a Rust observer action or injected state.
        page.mouse.click(140, 283)
        second = chat("research-empty", research, "draft_empty", False)
        click(second, "composer")
        page.keyboard.type("research-draft")
        second = chat("research-typed", research, "draft_matches_research", False)
        page.set_viewport_size({"width": 800, "height": 560})
        short = chat("short-research", research, "draft_matches_research", False)
        assert (
            short["controls"]["composer"]["uid"]
            == second["controls"]["composer"]["uid"]
        ), "Same adaptive owner was replaced within compact mode"
        page.set_viewport_size({"width": 1180, "height": 760})
        chat("wide-research", research, "draft_matches_research", True)
        # Return through actual room-list navigation and verify both drafts
        # remain distinct even after repeated owner retirement.
        page.set_viewport_size({"width": 520, "height": 760})
        compact = chat(
            "compact-research-again", research, "draft_matches_research", False
        )
        click(compact, "back")
        settle(
            "room-list-again",
            lambda s: (
                s["selected_room"] is None
                and not s["stack_transitioning"]
                and s["controls"]["rooms_list"]["valid"]
            ),
        )
        page.mouse.click(140, 207)
        chat("design-restored", design, "draft_matches_fixture", False)
        page.set_viewport_size({"width": 1180, "height": 760})
        chat("wide-design-return", design, "draft_matches_fixture", True)
    finally:
        (out / "web-adaptive-handoff.json").write_text(
            json.dumps(
                {
                    "fixture": True,
                    "liveAccounts": False,
                    "submissionKeysSent": False,
                    "activeSdkReplyEditQualified": False,
                    "trace": trace,
                },
                indent=2,
            )
        )
