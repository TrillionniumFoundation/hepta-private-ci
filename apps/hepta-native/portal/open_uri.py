#!/usr/bin/env python3
"""Hand an already-open, Rust-verified resource FD to XDG OpenURI.

stdin is the validated resource capability. The path string is deliberately
not supplied to this process or reopened after final-use admission.
"""

from __future__ import annotations

import os
import sys
import time

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except Exception as error:  # pragma: no cover - exercised on physical hosts
    print(f"XDG portal Python bindings are unavailable: {error}", file=sys.stderr)
    raise SystemExit(70)

DESTINATION = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
OPEN_URI_IFACE = "org.freedesktop.portal.OpenURI"
REQUEST_IFACE = "org.freedesktop.portal.Request"
MAXIMUM_SECONDS = 30


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def request_path(connection: Gio.DBusConnection, token: str) -> str:
    unique_name = connection.get_unique_name()
    if not unique_name or not unique_name.startswith(":"):
        fail("session bus did not assign a unique sender name", 71)
    sender = unique_name[1:].replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def main() -> int:
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in ("open", "reveal"):
        fail("expected open or reveal portal action", 64)
    try:
        os.fstat(0)
    except OSError as error:
        fail(f"verified resource descriptor is unavailable: {error}", 65)

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = f"hepta_resource_{os.getpid()}_{time.monotonic_ns()}"
    expected_path = request_path(connection, token)
    loop = GLib.MainLoop()
    state: dict[str, object] = {
        "done": False,
        "exit": 1,
        "handle": expected_path,
        "subscriptions": [],
    }

    def finish(exit_code: int, message: str | None = None) -> None:
        if bool(state["done"]):
            return
        state["done"] = True
        state["exit"] = exit_code
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
            response, _results = parameters.unpack()
            if int(response) == 0:
                finish(0)
            elif int(response) == 1:
                finish(74, message="resource handoff was cancelled")
            else:
                finish(75, message=f"resource handoff was rejected: {response}")
        except BaseException as error:
            finish(75, message=f"invalid OpenURI portal response: {error}")

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

    subscribe(expected_path)
    fd_list = Gio.UnixFDList.new()
    handle_index = fd_list.append(0)
    options = {
        "handle_token": GLib.Variant("s", token),
        "writable": GLib.Variant("b", False),
        "ask": GLib.Variant("b", False),
    }
    method = "OpenFile" if action == "open" else "OpenDirectory"
    reply, _out_fds = connection.call_with_unix_fd_list_sync(
        DESTINATION,
        DESKTOP_PATH,
        OPEN_URI_IFACE,
        method,
        GLib.Variant("(sha{sv})", ("", handle_index, options)),
        GLib.VariantType.new("(o)"),
        Gio.DBusCallFlags.NONE,
        15_000,
        fd_list,
        None,
    )
    returned_path = str(reply.unpack()[0])
    state["handle"] = returned_path
    if returned_path != expected_path:
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
        finish(124, message="resource handoff observation deadline exceeded")
        return GLib.SOURCE_REMOVE

    GLib.timeout_add_seconds(MAXIMUM_SECONDS, on_timeout)
    loop.run()
    for subscription in state["subscriptions"]:
        connection.signal_unsubscribe(subscription)
    return int(state["exit"])


if __name__ == "__main__":
    raise SystemExit(main())
