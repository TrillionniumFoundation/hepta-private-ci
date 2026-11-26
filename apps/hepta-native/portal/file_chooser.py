#!/usr/bin/env python3
"""Bounded XDG Desktop Portal file chooser adapter.

The Rust owner embeds and executes this static program through an absolute
/usr/bin/python3 path with an isolated interpreter. The selected URI is still
untrusted input; the native owner reopens and validates it before use.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.parse

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except Exception as error:  # pragma: no cover - exercised on physical hosts
    print(f"XDG portal Python bindings are unavailable: {error}", file=sys.stderr)
    raise SystemExit(70)

DESTINATION = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
FILE_CHOOSER_IFACE = "org.freedesktop.portal.FileChooser"
REQUEST_IFACE = "org.freedesktop.portal.Request"
MAXIMUM_SECONDS = 120
MAXIMUM_URI_BYTES = 16 * 1024


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def request_path(connection: Gio.DBusConnection, token: str) -> str:
    unique_name = connection.get_unique_name()
    if not unique_name or not unique_name.startswith(":"):
        fail("session bus did not assign a unique sender name", 71)
    sender = unique_name[1:].replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def decode_selected_uri(uri: str) -> str:
    if len(uri.encode("utf-8")) > MAXIMUM_URI_BYTES:
        fail("portal returned an oversized URI", 72)
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        fail("portal returned a non-local file URI", 72)
    try:
        raw_path = urllib.parse.unquote_to_bytes(parsed.path)
        path = raw_path.decode("utf-8", "strict")
    except (UnicodeDecodeError, ValueError) as error:
        fail(f"portal returned a non-UTF-8 file path: {error}", 72)
    if "\x00" in path or not os.path.isabs(path):
        fail("portal returned an invalid local path", 72)
    return path


def main() -> int:
    deadline = time.monotonic() + MAXIMUM_SECONDS
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = f"hepta_native_{os.getpid()}_{time.monotonic_ns()}"
    expected_path = request_path(connection, token)
    loop = GLib.MainLoop()
    state: dict[str, object] = {
        "done": False,
        "exit": 1,
        "path": None,
        "handle": expected_path,
        "subscriptions": [],
    }

    def finish(exit_code: int, path: str | None = None, message: str | None = None) -> None:
        if bool(state["done"]):
            return
        state["done"] = True
        state["exit"] = exit_code
        state["path"] = path
        if message:
            print(message, file=sys.stderr)
        loop.quit()

    def on_response(
        _connection: Gio.DBusConnection,
        _sender_name: str,
        _object_path: str,
        _interface_name: str,
        _signal_name: str,
        parameters: GLib.Variant,
        _user_data: object,
    ) -> None:
        try:
            response, results = parameters.unpack()
            if int(response) == 1:
                finish(0)
                return
            if int(response) != 0:
                finish(73, message=f"portal file chooser rejected the request: {response}")
                return
            uris = results.get("uris", [])
            if len(uris) != 1:
                finish(72, message=f"portal returned {len(uris)} selections; exactly one is required")
                return
            finish(0, path=decode_selected_uri(str(uris[0])))
        except BaseException as error:  # callback failures terminate deterministically
            finish(72, message=f"invalid portal file chooser response: {error}")

    def subscribe(path: str) -> None:
        subscription = connection.signal_subscribe(
            DESTINATION,
            REQUEST_IFACE,
            "Response",
            path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
            None,
        )
        subscriptions = state["subscriptions"]
        assert isinstance(subscriptions, list)
        subscriptions.append(subscription)

    # Subscribe to the deterministic request path before the method call so a
    # fast portal response cannot race past the observer.
    subscribe(expected_path)
    options = {
        "handle_token": GLib.Variant("s", token),
        "multiple": GLib.Variant("b", False),
        "directory": GLib.Variant("b", False),
        "modal": GLib.Variant("b", True),
    }
    reply = connection.call_sync(
        DESTINATION,
        DESKTOP_PATH,
        FILE_CHOOSER_IFACE,
        "OpenFile",
        GLib.Variant("(ssa{sv})", ("", "Select a Hepta input file", options)),
        GLib.VariantType.new("(o)"),
        Gio.DBusCallFlags.NONE,
        30_000,
        None,
    )
    returned_path = str(reply.unpack()[0])
    state["handle"] = returned_path
    if returned_path != expected_path:
        # Older portals may ignore handle_token. Keep the pre-subscribed path
        # and additionally observe the returned path without weakening bounds.
        subscribe(returned_path)

    def on_timeout() -> bool:
        if bool(state["done"]):
            return GLib.SOURCE_REMOVE
        handle = str(state["handle"])
        try:
            connection.call_sync(
                DESTINATION,
                handle,
                REQUEST_IFACE,
                "Close",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                5_000,
                None,
            )
        except Exception:
            pass
        finish(124, message="portal file chooser observation deadline exceeded")
        return GLib.SOURCE_REMOVE

    # Synchronous method dispatch must not restart the observation budget.
    # A response dispatched during that call may already have finished the
    # request; reentering the loop after quit would otherwise wait forever.
    if not bool(state["done"]):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            on_timeout()
        else:
            timer = GLib.timeout_add(remaining_ms, on_timeout)
            loop.run()
            if int(state["exit"]) != 124:
                GLib.source_remove(timer)
    for subscription in state["subscriptions"]:
        connection.signal_unsubscribe(subscription)
    selected = state["path"]
    if isinstance(selected, str):
        sys.stdout.write(selected)
        sys.stdout.flush()
    return int(state["exit"])


if __name__ == "__main__":
    raise SystemExit(main())
