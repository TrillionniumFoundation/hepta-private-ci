"""Bounded, non-submitting interaction evidence from the actual Rust canvas."""

import json
import time
from urllib.parse import urlsplit

MARKER = "[hepta-ui-observation] "
LOWER = (
    "apple_button",
    "facebook_button",
    "github_button",
    "gitlab_button",
    "google_button",
    "twitter_button",
    "signup_button",
)
TAB_TARGETS = (
    "user_id_input",
    "password_input",
    "homeserver_input",
    "login_button",
    *LOWER,
)


def focused(snapshot):
    names = [name for name, value in snapshot["controls"].items() if value["focused"]]
    assert len(names) <= 1, "Multiple Rust controls reported key focus"
    return names[0] if names else None


def fully_visible(control, viewport=(800, 560)):
    x, y, w, h = control["clipped"]
    full_w, full_h = control["size"]
    return (
        control["valid"]
        and full_w > 0
        and full_h > 0
        and abs(w - full_w) <= 1
        and abs(h - full_h) <= 1
        and x >= 0
        and y >= 0
        and x + w <= viewport[0] + 1
        and y + h <= viewport[1] + 1
    )


def assess(initial_tab, forward, backward, scrolled, drafts, no_submit):
    return {
        "initialTabStartsAtFirstInput": focused(initial_tab) == "user_id_input",
        "forwardTabReachesAllControls": set(TAB_TARGETS)
        <= {focused(s) for s in forward},
        "reverseTabReachesAllControls": set(TAB_TARGETS)
        <= {focused(s) for s in backward},
        "wheelShowsAllLowerControls": all(
            fully_visible(scrolled["controls"][n]) for n in LOWER
        ),
        "draftPreserved": bool(drafts)
        and all(s["draft_matches_fixture"] for s in drafts),
        "noSubmission": no_submit,
    }


def capture_login_usability(browser, origin, out):
    context = browser.new_context(
        viewport={"width": 800, "height": 560}, device_scale_factor=1
    )
    samples, messages, failures, responses, wasm = [], [], [], [], []
    report = {
        "fixture": True,
        "viewport": [800, 560],
        "liveAccounts": False,
        "submissionKeysSent": False,
        "checks": {},
        "steps": [],
        "screenshots": [],
    }

    def route(request_route):
        url = request_route.request.url
        if urlsplit(url).path == "/$report_error" or not url.startswith(
            (origin + "/", "data:", "blob:")
        ):
            failures.append("Forbidden request: " + urlsplit(url).path)
            request_route.abort()
        else:
            request_route.continue_()

    context.route("**/*", route)
    page = context.new_page()
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.on(
        "requestfailed",
        lambda request: failures.append(
            "Request failed: " + urlsplit(request.url).path
        ),
    )
    page.on("popup", lambda _: failures.append("Unexpected popup"))

    def console(message):
        messages.append(f"{message.type}: {message.text}")
        if MARKER in message.text:
            samples.append(json.loads(message.text.split(MARKER, 1)[1]))

    page.on("console", console)

    def response_received(response):
        responses.append(
            {"path": urlsplit(response.url).path, "status": response.status}
        )
        if not response.ok:
            failures.append(f"HTTP {response.status}: " + urlsplit(response.url).path)
        if response.url.endswith(".wasm") and response.ok:
            wasm.append(urlsplit(response.url).path)

    page.on("response", response_received)

    def snapshot(label):
        # Read a later timer sample, after Makepad's pending focus cycle and draw.
        previous = samples[-1]["sequence"] if samples else 0
        deadline = time.monotonic() + 3
        while not samples or samples[-1]["sequence"] <= previous + 1:
            assert time.monotonic() < deadline, "No fresh real-widget observation"
            page.wait_for_timeout(50)
        state = samples[-1]
        report["steps"].append({"input": label, "observation": state})
        return state

    def screenshot(label):
        from qualify import digest

        path = out / f"web-login-short-usability-{label}.png"
        page.screenshot(path=str(path))
        report["screenshots"].append({"png": path.name, "sha256": digest(path)})

    try:
        url = origin + "/?hepta-ui-fixture=login-usability"
        page.goto(url, wait_until="networkidle")
        page.locator("canvas").first.wait_for(state="visible", timeout=60000)
        page.locator(".canvas_loader").wait_for(state="hidden", timeout=60000)
        assert wasm, "No real WASM fetched for usability check"
        initial = snapshot("initial; no pointer click")
        assert initial["controls"]["user_id_input"]["valid"], (
            "Actual input geometry unavailable"
        )
        page.keyboard.press("Tab")
        initial_tab = snapshot("Tab from initial state")
        screenshot("initial-tab")

        x, y, w, h = initial_tab["controls"]["user_id_input"]["clipped"]
        assert fully_visible(initial_tab["controls"]["user_id_input"])
        page.mouse.click(x + w / 2, y + h / 2)
        clicked = snapshot("real pointer click on first input")
        assert focused(clicked) == "user_id_input", (
            "First input did not take real pointer focus"
        )
        page.keyboard.type("reachability-fixture")
        typed = snapshot("type fixed synthetic draft")
        assert typed["draft_matches_fixture"], "Synthetic draft not present"
        forward, backward, drafts = [typed], [], [typed]
        # Fixed finite traversal; repeated/stalled focus is recorded, never forced.
        for label, key, trace in (
            ("forward", "Tab", forward),
            ("reverse", "Shift+Tab", backward),
        ):
            for index in range(len(TAB_TARGETS) + 3):
                page.keyboard.press(key)
                state = snapshot(f"{label} {index + 1}: {key}")
                trace.append(state)
                drafts.append(state)
        screenshot("keyboard")

        page.mouse.move(200, 450)
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1000)
        scrolled = snapshot("wheel down without activation")
        drafts.append(scrolled)
        screenshot("wheel")
        page.mouse.wheel(0, -900)
        page.wait_for_timeout(1000)
        returned = snapshot("wheel back to first input")
        drafts.append(returned)
        report["checks"] = assess(
            initial_tab, forward, backward, scrolled, drafts, page.url == url
        )
        fonts = [r["path"] for r in responses if r["path"].endswith((".ttf", ".otf"))]
        report["checks"]["fontsFetchedOnce"] = len(fonts) == 7 and len(set(fonts)) == 7
        report["focusTrace"] = {
            "initial": focused(initial),
            "initialTab": focused(initial_tab),
            "forward": [focused(s) for s in forward],
            "reverse": [focused(s) for s in backward],
        }
    except Exception as error:
        failures.append(f"{type(error).__name__}: {error}")
    finally:
        failures.extend(message for message in messages if message.startswith("error:"))
        report["failures"] = failures
        report["passed"] = (
            bool(report["checks"]) and all(report["checks"].values()) and not failures
        )
        report["runtime"] = {"wasm": wasm, "responses": responses}
        (out / "web-login-short-usability.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        (out / "web-login-short-usability.log").write_text("\n".join(messages))
        context.close()
    return report
