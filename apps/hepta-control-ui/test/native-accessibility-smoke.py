#!/usr/bin/env python3
"""Exercise a caller-created native Makepad window on an isolated X11/AT-SPI bus.

Requires system Python with pyatspi and xdotool. The caller owns Xvfb, D-Bus,
the app process and temporary XDG state. This script never starts/stops an owner
or claims that synthesized keyboard input is physical IME/Orca acceptance.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import pyatspi


def wait_for(probe, label, timeout=12):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except Exception as caught:
            error = caught
        time.sleep(0.05)
    raise AssertionError(f"Timed out: {label}; last error: {error}")


def children(node):
    for index in range(node.childCount):
        child = node.getChildAtIndex(index)
        if child is not None:
            yield child


def walk(node):
    pending = [node]
    for _ in range(4096):
        if not pending:
            return
        item = pending.pop()
        yield item
        pending.extend(reversed(list(children(item))))
    raise AssertionError("AT-SPI tree exceeded the traversal bound")


def click(node):
    action = node.queryAction()
    names = [action.getName(index) for index in range(action.nActions)]
    index = next(index for index, name in enumerate(names) if name.lower() in {"click", "press", "activate"})
    assert action.doAction(index), (node.name, names)


def run(args, receipt):
    window_pid = int(subprocess.check_output(["xdotool", "getwindowpid", args.window_id], text=True))
    assert window_pid == args.pid, "The selected X11 window belongs to another process"
    desktop = pyatspi.Registry.getDesktop(0)
    app = wait_for(lambda: next((node for node in children(desktop) if node.get_process_id() == args.pid), None), "exact process registration")

    def named(name):
        return next((node for node in walk(app) if node.name == name), None)

    def editor():
        return wait_for(lambda: named("Message / 消息"), "original message editor")

    def value():
        return editor().queryText().getText(0, -1)

    def record(name):
        receipt["checks"].append({"name": name, "passed": True})

    field = editor()
    initial = value()
    assert field.queryComponent().grabFocus()
    subprocess.run(["xdotool", "windowfocus", "--sync", args.window_id], check=True)
    wait_for(lambda: editor().getState().contains(pyatspi.STATE_FOCUSED), "native editor focus")
    record("actual-AT-SPI-role-name-and-focus")

    sample = "中文 e\u0301 👨‍👩‍👧‍👦\n第二行"
    assert field.queryEditableText().setTextContents(sample)
    wait_for(lambda: value() == sample, "CJK grapheme edit through the original reducer")
    record("CJK-combining-emoji-multiline-edit")

    text = editor().queryText()
    assert text.addSelection(0, 2)
    wait_for(lambda: tuple(editor().queryText().getSelection(0)) == (0, 2), "two CJK characters selected")
    record("UTF-8-selection-offsets")

    # Oversized requests must not replace the selected valid text.
    editor().queryEditableText().setTextContents("界" * 6000)
    time.sleep(0.3)
    assert value() == sample
    assert tuple(editor().queryText().getSelection(0)) == (0, 2)
    record("oversized-accessibility-edit-preserves-text-and-selection")

    subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+z"], check=True)
    wait_for(lambda: value() == initial, "original SDK undo")
    subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+shift+z"], check=True)
    wait_for(lambda: value() == sample, "original SDK redo")
    record("native-keyboard-undo-redo")

    send = wait_for(lambda: named("Send"), "original Send control")
    assert not send.getState().contains(pyatspi.STATE_ENABLED), "No owner host was installed in this test"
    record("unauthenticated-Send-remains-disabled")

    stale_editor = editor()
    click(wait_for(lambda: named("+ New draft"), "original New draft control"))
    wait_for(lambda: value() == "", "original new-room action")
    try:
        stale_editor.queryEditableText().setTextContents("late stale room edit")
    except Exception:
        pass  # Defunct AT-SPI object is also a valid stale-node refusal.
    time.sleep(0.3)
    assert value() == ""
    record("stale-accessibility-node-cannot-edit-new-room")

    receipt["tree"] = [{"role": node.getRoleName(), "name": node.name} for node in walk(app)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    result = {"schema": "hepta.native-atspi-smoke.v1", "pid": options.pid,
              "scope": "original Makepad AT-SPI actions and synthesized X11 keyboard; no physical IME or Orca listening claim",
              "checks": [], "passed": False}
    try:
        run(options, result)
        result["passed"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
