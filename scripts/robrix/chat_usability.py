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
