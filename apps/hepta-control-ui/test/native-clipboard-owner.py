#!/usr/bin/env python3
"""One caller-owned GTK clipboard reply held for an actual stale-target test.

Test-only clipboard ownership on the harness's private X11 display. This is not
a UI driver, input injector, alternate renderer or product service. The caller
must release one selection response through stdin within the bounded deadline.
"""
import argparse
import json
import select
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk


def emit(event):
    print(json.dumps({"event": event, "monotonic": time.monotonic()}), flush=True)


def run(text):
    Gtk.init([])
    owner = Gtk.Invisible()
    owner.realize()
    complete = False

    def respond(_owner, selection, _info, _timestamp):
        nonlocal complete
        emit("requested")
        readable, _, _ = select.select([sys.stdin], [], [], 1.8)
        if not readable or sys.stdin.readline() != "release\n":
            emit("refused")
            complete = True
            return
        selection.set_text(text, -1)
        emit("answered")
        complete = True

    owner.connect("selection-get", respond)
    Gtk.selection_add_target(owner, Gdk.SELECTION_CLIPBOARD, Gdk.Atom.intern("UTF8_STRING", False), 1)
    if not Gtk.selection_owner_set(owner, Gdk.SELECTION_CLIPBOARD, Gdk.CURRENT_TIME):
        raise RuntimeError("Cannot own the harness clipboard")
    emit("ready")
    deadline = time.monotonic() + 8
    context = GLib.MainContext.default()
    while not complete and time.monotonic() < deadline:
        if context.pending():
            context.iteration(False)
        else:
            time.sleep(0.005)
    # GDK must flush the selection response before retiring its owned window.
    Gdk.Display.get_default().flush()
    until = time.monotonic() + 0.2
    while time.monotonic() < until:
        if context.pending():
            context.iteration(False)
        else:
            time.sleep(0.005)
    owner.destroy()
    if not complete:
        raise RuntimeError("No native clipboard request arrived")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    options = parser.parse_args()
    if len(options.text.encode()) > 65536 or "\0" in options.text:
        parser.error("Test clipboard payload must be bounded text")
    run(options.text)
