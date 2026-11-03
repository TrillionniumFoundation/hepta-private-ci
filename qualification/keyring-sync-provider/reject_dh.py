"""Private D-Bus fixture rejecting encrypted sessions, with no plaintext retry."""

import json
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib


class RejectSession(dbus.service.Object):
    @dbus.service.method(
        "org.freedesktop.Secret.Service", in_signature="sv", out_signature="vo"
    )
    def OpenSession(self, algorithm, value):
        with open(sys.argv[1], "a") as log:
            log.write(json.dumps({"algorithm": str(algorithm)}) + "\n")
        raise dbus.exceptions.DBusException(
            "encrypted session deliberately rejected",
            name="org.freedesktop.DBus.Error.NotSupported",
        )


DBusGMainLoop(set_as_default=True)
connection = dbus.SessionBus()
name = dbus.service.BusName("org.freedesktop.secrets", connection)
service = RejectSession(connection, "/org/freedesktop/secrets")
print("READY", flush=True)
GLib.MainLoop().run()
