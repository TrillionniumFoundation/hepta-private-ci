#!/usr/bin/env python3
"""Exercise actual original Makepad EditableText on a caller-owned private bus.

This tests the five implemented atomic methods. PasteText must explicitly
refuse while the original SDK lacks a request-scoped clipboard-read API; the
receipt therefore never claims full EditableText or human Orca qualification.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import gi
gi.require_version("Atspi", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Atspi, Gdk, GLib, Gtk

SPEC = importlib.util.spec_from_file_location("original_atspi_test", Path(__file__).with_name("native-accessibility-smoke.py"))
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def settle(seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        context = GLib.MainContext.default()
        for _ in range(128):
            if not context.pending():
                break
            context.iteration(False)
        time.sleep(0.01)


def run(args, result):
    xid = int(args.window_id, 0)
    assert int(subprocess.check_output(["xdotool", "getwindowpid", args.window_id], text=True)) == args.pid
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    app = SMOKE.wait_for(lambda: next((node for node in SMOKE.children(desktop) if node.get_process_id() == args.pid), None), "exact original process")

    def named(name):
        return next((node for node in SMOKE.walk(app) if node.get_name() == name), None)

    def editor():
        return SMOKE.wait_for(lambda: named("Message / 消息"), "original editor")

    def editable():
        return SMOKE.wait_for(lambda: editor().get_editable_text_iface(), "real D-Bus EditableText interface")

    def value():
        return editor().get_text_iface().get_text(0, -1)

    def key(name):
        assert int(subprocess.check_output(["xdotool", "getwindowfocus"], text=True)) == xid
        subprocess.run(["xdotool", "key", "--clearmodifiers", name], check=True, timeout=5)

    def record(name):
        result["checks"].append({"name": name, "passed": True})

    def refused(operation):
        try:
            assert operation() is False, "Invalid request was accepted for dispatch"
        except GLib.Error:
            pass

    Gtk.init([])
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard_state = {"pending": False, "value": None}

    def clipboard_is(expected):
        def received(_clipboard, text, _data):
            clipboard_state.update(pending=False, value=text)
        if not clipboard_state["pending"]:
            clipboard_state["pending"] = True
            clipboard.request_text(received, None)
        return clipboard_state["value"] == expected

    subprocess.run(["xdotool", "windowfocus", "--sync", args.window_id], check=True, timeout=5)
    assert editor().get_component_iface().grab_focus()
    SMOKE.wait_for(lambda: editor().get_state_set().contains(Atspi.StateType.FOCUSED), "original editor focus")
    assert value() == "", "Run after the standard native smoke leaves a blank local room"
    initial = value()
    sample = "中文 e\u0301 👨‍👩‍👧‍👦\n第二行"
    assert editable().set_text_contents(sample)
    SMOKE.wait_for(lambda: value() == sample, "atomic complete CJK text")
    record("standard-EditableText-set-complete-CJK-graphemes")

    # Character position and byte length are intentionally different.
    assert editable().insert_text(1, "你尾", 3)
    SMOKE.wait_for(lambda: value() == "中你文" + sample[2:], "byte-bounded CJK insertion")
    key("ctrl+z")
    SMOKE.wait_for(lambda: value() == sample, "original undo after semantic insertion")
    key("ctrl+shift+z")
    SMOKE.wait_for(lambda: value() == "中你文" + sample[2:], "original redo after semantic insertion")
    key("ctrl+z")
    SMOKE.wait_for(lambda: value() == sample, "return to exact original sample")
    record("standard-EditableText-byte-prefix-and-original-undo-redo")

    clipboard.set_text("owned test sentinel", -1)
    assert editable().copy_text(0, 2)
    SMOKE.wait_for(lambda: clipboard_is("中文"), "copy reached the original native clipboard")
    assert value() == sample
    clipboard.set_text("owned cut sentinel", -1)
    clipboard_state["value"] = None
    assert editable().cut_text(0, 2)
    SMOKE.wait_for(lambda: value() == sample[2:], "atomic cut of selected CJK range")
    SMOKE.wait_for(lambda: clipboard_is("中文"), "cut used the original clipboard")
    key("ctrl+z")
    SMOKE.wait_for(lambda: value() == sample, "original undo after semantic cut")
    assert editable().delete_text(0, 2)
    SMOKE.wait_for(lambda: value() == sample[2:], "atomic CJK deletion")
    key("ctrl+z")
    SMOKE.wait_for(lambda: value() == sample, "original undo after semantic deletion")
    record("standard-EditableText-copy-cut-delete-use-original-editor-and-clipboard")

    refused(lambda: editable().set_text_contents("界" * 6000))
    refused(lambda: editable().insert_text(0, "界" * 6000, 18000))
    refused(lambda: editable().insert_text(0, "你", 1))
    refused(lambda: editable().insert_text(4, "x", 1))  # Inside e + combining acute.
    refused(lambda: editable().delete_text(3, 4))
    refused(lambda: editable().delete_text(2, 1))
    refused(lambda: editable().delete_text(-1, 1))
    settle(0.4)
    assert value() == sample
    key("ctrl+z")
    SMOKE.wait_for(lambda: value() == initial, "invalid requests retained the prior undo history")
    key("ctrl+shift+z")
    SMOKE.wait_for(lambda: value() == sample, "original redo after refused external requests")
    record("standard-EditableText-limit-UTF8-grapheme-and-range-refusals-preserve-history")

    # A false result is a documented missing SDK primitive, never a full pass.
    assert editable().paste_text(0) is False
    settle(0.2)
    assert value() == sample
    result["paste_text"] = "explicitly-unavailable-no-mutation"

    old = editable()
    SMOKE.click(SMOKE.wait_for(lambda: named("+ New draft"), "original room action"))
    SMOKE.wait_for(lambda: value() == "", "new original room")
    assert editable().set_text_contents("new room")
    SMOKE.wait_for(lambda: value() == "new room", "new-room semantic edit")
    refused(lambda: old.set_text_contents("stale room request"))
    settle(0.4)
    assert value() == "new room"
    record("stale-EditableText-object-cannot-edit-another-original-room")
    assert editable().set_text_contents("")
    SMOKE.wait_for(lambda: value() == "", "blank room for real IBus stage")
    clipboard.clear()
    result["supported_methods_passed"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    receipt = {"schema": "hepta.native-atomic-editable-text.v1", "pid": options.pid,
               "passed": False, "checks": [], "supported_methods_passed": False,
               "full_editable_text_qualified": False, "orca_human_evaluation": False,
               "physical_keyboard_qualified": False, "synthetic_ime_events_used": False}
    try:
        run(options, receipt)
        receipt["passed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
