#!/usr/bin/python3
"""Isolated, in-memory Secret Service fixture; only synthetic credentials allowed.

Run under dbus-run-session. This exercises the real encrypted D-Bus transports,
not a monkey-patched Rust CredentialBuilder. No credential payload is logged.
"""

import json
import os
import secrets
import sys
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT = "/org/freedesktop/secrets"
COLLECTION = ROOT + "/collection/fixture"
SERVICE = "org.freedesktop.Secret.Service"
ITEM = "org.freedesktop.Secret.Item"
COLLECTION_IFACE = "org.freedesktop.Secret.Collection"
SESSION = "org.freedesktop.Secret.Session"
DH = "dh-ietf1024-sha256-aes128-cbc-pkcs7"
PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE65381FFFFFFFFFFFFFFFF",
    16,
)
XML = """<node>
<interface name="org.freedesktop.Secret.Service">
<method name="OpenSession"><arg direction="in" type="s"/><arg direction="in" type="v"/><arg direction="out" type="v"/><arg direction="out" type="o"/></method>
<method name="SearchItems"><arg direction="in" type="a{ss}"/><arg direction="out" type="ao"/><arg direction="out" type="ao"/></method>
<method name="ReadAlias"><arg direction="in" type="s"/><arg direction="out" type="o"/></method>
<method name="Unlock"><arg direction="in" type="ao"/><arg direction="out" type="ao"/><arg direction="out" type="o"/></method>
<property name="Collections" type="ao" access="read"/>
</interface>
<interface name="org.freedesktop.Secret.Collection">
<method name="CreateItem"><arg direction="in" type="a{sv}"/><arg direction="in" type="(oayays)"/><arg direction="in" type="b"/><arg direction="out" type="o"/><arg direction="out" type="o"/></method>
<method name="SearchItems"><arg direction="in" type="a{ss}"/><arg direction="out" type="ao"/></method>
<property name="Items" type="ao" access="read"/>
<property name="Locked" type="b" access="read"/>
<property name="Label" type="s" access="read"/>
</interface>
<interface name="org.freedesktop.Secret.Item">
<method name="GetSecret"><arg direction="in" type="o"/><arg direction="out" type="(oayays)"/></method>
<method name="SetSecret"><arg direction="in" type="(oayays)"/></method>
<method name="Delete"><arg direction="out" type="o"/></method>
<property name="Locked" type="b" access="read"/>
<property name="Attributes" type="a{ss}" access="read"/>
<property name="Label" type="s" access="read"/>
</interface>
<interface name="org.freedesktop.Secret.Session"><method name="Close"/></interface>
</node>"""


class Fixture:
    def __init__(self, receipt_path):
        self.receipt_path = Path(receipt_path)
        self.account = os.environ["HEPTA_KEYRING_TEST_ACCOUNT"]
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.interfaces = {
            i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces
        }
        self.items = {}
        self.sessions = {}
        self.events = []
        self.counter = 0
        self.session_counter = 0
        self.register(ROOT, SERVICE)
        self.register(COLLECTION, COLLECTION_IFACE)
        for service in [
            "ambiguous",
            "ambiguous",
            "locked",
            "read_failure",
            "write_failure",
            "delete_failure",
        ]:
            self.add_item(
                self.attributes(service, self.account),
                (service + "-synthetic").encode(),
                service == "locked",
            )
        self.owner = Gio.bus_own_name_on_connection(
            self.connection,
            "org.freedesktop.secrets",
            Gio.BusNameOwnerFlags.NONE,
            self.acquired,
            None,
        )

    @staticmethod
    def attributes(service, account):
        return {
            "service": service,
            "username": account,
            "target": "default",
            "application": "rust-keyring",
        }

    def register(self, path, interface):
        return self.connection.register_object(
            path, self.interfaces[interface], self.method, self.property, None
        )

    def add_item(self, attributes, secret, locked=False):
        self.counter += 1
        path = COLLECTION + f"/item{self.counter}"
        registration = self.register(path, ITEM)
        self.items[path] = {
            "attributes": dict(attributes),
            "secret": secret,
            "locked": locked,
            "registration": registration,
        }
        return path

    def acquired(self, *_):
        print("READY", flush=True)
        self.persist()

    def persist(self):
        self.receipt_path.write_text(
            json.dumps(
                {
                    "synthetic_only": True,
                    "transport": "private dbus-run-session",
                    "events": self.events,
                    "remaining_items": len(self.items),
                },
                indent=2,
            )
            + "\n"
        )

    def event(self, **fields):
        self.events.append(fields)
        self.persist()

    def property(self, connection, sender, path, interface, prop):
        if interface == SERVICE and prop == "Collections":
            return GLib.Variant("ao", [COLLECTION])
        if interface == COLLECTION_IFACE:
            return {
                "Items": GLib.Variant("ao", list(self.items)),
                "Locked": GLib.Variant("b", False),
                "Label": GLib.Variant("s", "Synthetic fixture"),
            }[prop]
        item = self.items[path]
        return {
            "Locked": GLib.Variant("b", item["locked"]),
            "Attributes": GLib.Variant("a{ss}", item["attributes"]),
            "Label": GLib.Variant("s", "Synthetic fixture item"),
        }[prop]

    def decrypt(self, value):
        session, iv, encrypted, mime = value
        decryptor = Cipher(
            algorithms.AES(self.sessions[session]), modes.CBC(bytes(iv))
        ).decryptor()
        padded = decryptor.update(bytes(encrypted)) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        result = unpadder.update(padded) + unpadder.finalize()
        assert bytes(encrypted) != result
        self.event(
            operation="decrypt",
            algorithm=DH,
            iv_bytes=len(iv),
            ciphertext_bytes=len(encrypted),
            plaintext_bytes=len(result),
            encrypted=True,
        )
        return result

    def encrypt(self, session, secret):
        iv = secrets.token_bytes(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(secret) + padder.finalize()
        encryptor = Cipher(
            algorithms.AES(self.sessions[session]), modes.CBC(iv)
        ).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        self.event(operation="encrypt", algorithm=DH, encrypted=True)
        return (session, list(iv), list(encrypted), "text/plain")

    def method(
        self, connection, sender, path, interface, method, parameters, invocation
    ):
        args = parameters.unpack()
        self.event(operation="method", interface=interface, method=method)
        try:
            if interface == SERVICE:
                if method == "OpenSession":
                    algorithm, client_public = args
                    assert algorithm == DH, "unencrypted session rejected"
                    private = secrets.randbits(1024)
                    public = pow(2, private, PRIME).to_bytes(128, "big")
                    common = pow(
                        int.from_bytes(bytes(client_public), "big"), private, PRIME
                    ).to_bytes(128, "big")
                    key = HKDF(
                        algorithm=hashes.SHA256(), length=16, salt=None, info=b""
                    ).derive(common)
                    self.session_counter += 1
                    session = ROOT + f"/session/s{self.session_counter}"
                    self.sessions[session] = key
                    self.register(session, SESSION)
                    self.event(operation="open_session", algorithm=algorithm)
                    invocation.return_value(
                        GLib.Variant(
                            "(vo)", (GLib.Variant("ay", list(public)), session)
                        )
                    )
                elif method == "SearchItems":
                    found = [
                        p
                        for p, x in self.items.items()
                        if all(x["attributes"].get(k) == v for k, v in args[0].items())
                    ]
                    unlocked = [p for p in found if not self.items[p]["locked"]]
                    locked = [p for p in found if self.items[p]["locked"]]
                    invocation.return_value(GLib.Variant("(aoao)", (unlocked, locked)))
                elif method == "ReadAlias":
                    invocation.return_value(
                        GLib.Variant(
                            "(o)", (COLLECTION if args[0] == "default" else "/",)
                        )
                    )
                elif method == "Unlock":
                    for p in args[0]:
                        self.items[p]["locked"] = False
                    self.event(operation="unlock", count=len(args[0]))
                    invocation.return_value(GLib.Variant("(aoo)", (args[0], "/")))
                else:
                    raise AssertionError(method)
            elif interface == COLLECTION_IFACE:
                if method == "SearchItems":
                    found = [
                        p
                        for p, x in self.items.items()
                        if all(x["attributes"].get(k) == v for k, v in args[0].items())
                    ]
                    invocation.return_value(GLib.Variant("(ao)", (found,)))
                elif method == "CreateItem":
                    props, secret, replace = args
                    attrs = props[ITEM + ".Attributes"]
                    assert attrs["application"] == "rust-keyring"
                    assert attrs["service"] == "wsp-synthetic"
                    assert attrs["username"] == self.account
                    assert attrs["target"] == "default"
                    new_path = self.add_item(attrs, self.decrypt(secret))
                    self.event(operation="create", attributes=attrs, replace=replace)
                    invocation.return_value(GLib.Variant("(oo)", (new_path, "/")))
                else:
                    raise AssertionError(method)
            elif interface == ITEM:
                item = self.items[path]
                service = item["attributes"]["service"]
                failed = {
                    "GetSecret": "read_failure",
                    "SetSecret": "write_failure",
                    "Delete": "delete_failure",
                }.get(method) == service
                if failed:
                    self.event(operation="injected_failure", method=method)
                    invocation.return_dbus_error(
                        "org.freedesktop.DBus.Error.Failed",
                        "synthetic credential operation failure",
                    )
                elif method == "GetSecret":
                    invocation.return_value(
                        GLib.Variant(
                            "((oayays))", (self.encrypt(args[0], item["secret"]),)
                        )
                    )
                elif method == "SetSecret":
                    item["secret"] = self.decrypt(args[0])
                    invocation.return_value(GLib.Variant("()", ()))
                elif method == "Delete":
                    self.connection.unregister_object(item["registration"])
                    del self.items[path]
                    invocation.return_value(GLib.Variant("(o)", ("/",)))
                else:
                    raise AssertionError(method)
            elif interface == SESSION:
                assert method == "Close"
                self.sessions.pop(path, None)
                invocation.return_value(GLib.Variant("()", ()))
            else:
                raise AssertionError(interface)
        except Exception as error:
            self.event(
                operation="fixture_error", kind=type(error).__name__, error=str(error)
            )
            invocation.return_dbus_error("org.hepta.Fixture.Error", str(error))


if __name__ == "__main__":
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "private bus required"
    fixture = Fixture(sys.argv[1])
    GLib.MainLoop().run()
