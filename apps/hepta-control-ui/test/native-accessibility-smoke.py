#!/usr/bin/env python3
"""Exercise a caller-created native Makepad window on an isolated X11/AT-SPI bus.

Requires system Python with GI Atspi/GTK 3 and xdotool. The caller owns Xvfb, D-Bus,
the app process and temporary XDG state. This script never starts/stops an owner
or claims that synthesized keyboard input is physical IME/Orca acceptance.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path
from x11_client_owner import require_window_pid

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gdk, GLib, Gtk


def wait_for(probe, label, timeout=12):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            context = GLib.MainContext.default()
            for _ in range(128):
                if not context.pending():
                    break
                context.iteration(False)
            value = probe()
            if value:
                return value
        except Exception as caught:
            error = caught
        time.sleep(0.05)
    raise AssertionError(f"Timed out: {label}; last error: {error}")


def children(node):
    for index in range(node.get_child_count()):
        child = node.get_child_at_index(index)
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
    action = node.get_action_iface()
    names = [action.get_action_name(index) for index in range(action.get_n_actions())]
    index = next(index for index, name in enumerate(names) if name.lower() in {"click", "press", "activate"})
    assert action.do_action(index), (node.get_name(), names)


def run(args, receipt):
    receipt["x11_owner"] = require_window_pid(args.window_id, args.pid)
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    app = wait_for(lambda: next((node for node in children(desktop) if node.get_process_id() == args.pid), None), "exact process registration")

    def named(name):
        return next((node for node in walk(app) if node.get_name() == name), None)

    def editor():
        return wait_for(lambda: named("Message / 消息"), "original message editor")

    def value():
        return editor().get_text_iface().get_text(0, -1)

    def selection():
        selected = editor().get_text_iface().get_selection(0)
        return selected.start_offset, selected.end_offset

    def record(name):
        receipt["checks"].append({"name": name, "passed": True})

    def key(value):
        require_window_pid(args.window_id, args.pid)
        assert int(subprocess.check_output(["xdotool", "getwindowfocus"], text=True)) == int(args.window_id, 0)
        subprocess.run(["xdotool", "key", "--clearmodifiers", value], check=True, timeout=5)

    Gtk.init([])
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def paste(text):
        # AccessKit Unix 0.13.1 does not expose EditableText. Exercise the real
        # SDK paste transaction through this caller-owned X11 clipboard, while
        # using AT-SPI only for its supported text/selection/focus interfaces.
        clipboard.set_text(text, -1)
        key("ctrl+v")

    field = editor()
    initial = value()
    subprocess.run(["xdotool", "windowfocus", "--sync", args.window_id], check=True)
    assert field.get_component_iface().grab_focus()
    wait_for(lambda: editor().get_state_set().contains(Atspi.StateType.FOCUSED), "native editor focus")
    record("actual-AT-SPI-role-name-and-focus")

    sample = "中文 e\u0301 👨‍👩‍👧‍👦\n第二行"
    paste(sample)
    wait_for(lambda: value() == sample, "CJK grapheme edit through the original reducer")
    record("OS-clipboard-CJK-combining-emoji-multiline-transaction")

    text = editor().get_text_iface()
    assert text.add_selection(0, 2)
    wait_for(lambda: selection() == (0, 2), "two CJK characters selected")
    record("UTF-8-selection-offsets")

    # Oversized requests must not replace the selected valid text.
    paste("界" * 6000)
    wait_for(lambda: named("Draft exceeds the input limit or contains an unsupported NUL. Last valid text retained."), "original reducer reported rejected paste")
    wait_for(lambda: value() == sample and selection() == (0, 2), "oversized real clipboard transaction rolls back")
    assert value() == sample
    assert selection() == (0, 2)
    record("oversized-native-paste-preserves-text-selection-and-prior-undo")

    key("ctrl+z")
    wait_for(lambda: value() == initial, "original SDK undo")
    key("ctrl+shift+z")
    wait_for(lambda: value() == sample, "original SDK redo")
    record("native-keyboard-undo-redo")

    send = wait_for(lambda: named("Send"), "original Send control")
    assert not send.get_state_set().contains(Atspi.StateType.ENABLED), "No owner host was installed in this test"
    record("unauthenticated-Send-remains-disabled")

    stale_editor = editor()
    click(wait_for(lambda: named("+ New draft"), "original New draft control"))
    wait_for(lambda: value() == "", "original new-room action")
    assert editor().get_component_iface().grab_focus()
    paste("new room")
    wait_for(lambda: value() == "new room", "new original room editor")
    assert editor().get_text_iface().set_caret_offset(8)
    wait_for(lambda: editor().get_text_iface().get_caret_offset() == 8, "new-room caret")
    try:
        stale_editor.get_text_iface().set_caret_offset(0)
    except Exception:
        pass  # Defunct AT-SPI object is also a valid stale-node refusal.
    time.sleep(0.3)
    assert value() == "new room"
    assert editor().get_text_iface().get_caret_offset() == 8
    record("stale-accessibility-node-cannot-change-new-room-caret")
    key("ctrl+a")
    key("BackSpace")
    wait_for(lambda: value() == "", "empty new room for independent IME test")
    clipboard.clear()

    receipt["tree"] = [{"role": node.get_role_name(), "name": node.get_name()} for node in walk(app)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    result = {"schema": "hepta.native-atspi-smoke.v1", "pid": options.pid,
              "scope": "original Makepad AT-SPI focus/text/selection/actions plus real private-X11 clipboard/keyboard; EditableText, physical IME and Orca listening remain unqualified",
              "editable_text_interface_qualified": False,
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
