"""Single-use protected key pairing and candidate preparation; no live handoff."""

import base64
import pwd
from pathlib import Path
import secrets
import json
import time

import native_chat_install_io as io
import native_chat_install_plan as plan


def keyring_available(deadline, command):
    user = pwd.getpwuid(1000)
    out = command(
        [
            "/usr/sbin/runuser",
            "-u",
            user.pw_name,
            "--",
            "/usr/bin/gdbus",
            "call",
            "--address",
            "unix:path=/run/user/1000/bus",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.NameHasOwner",
            "org.freedesktop.secrets",
        ],
        deadline,
    )
    if out.strip() != b"(true,)":
        raise ValueError("the desktop operating-system keyring service is not running")


def source_access(checked, deadline, command):
    for uid, paths in (
        (984, [checked["request"]["gateway"]["path"]]),
        (
            1000,
            [
                checked["request"]["renderer"]["path"],
                checked["request"]["credential_helper"]["path"],
            ],
        ),
    ):
        user = pwd.getpwuid(uid)
        for path in paths:
            command(
                [
                    "/usr/sbin/runuser",
                    "-u",
                    user.pw_name,
                    "--",
                    "/usr/bin/test",
                    "-x",
                    path,
                ],
                deadline,
            )
    manifest = json.loads(
        io.read_public(checked["request"]["renderer_manifest"]["path"])
    )
    directory = Path(checked["request"]["renderer_manifest"]["path"]).parent
    files = [str(directory / entry["path"]) for entry in manifest["files"]]
    metadata_check = "import json,os,sys;sys.exit(0 if all(os.access(p,os.R_OK) for p in json.load(sys.stdin)) else 1)"
    command(
        [
            "/usr/sbin/runuser",
            "-u",
            pwd.getpwuid(1000).pw_name,
            "--",
            "/usr/bin/python3",
            "-I",
            "-c",
            metadata_check,
        ],
        deadline,
        io.encode(files),
    )


def prepare(checked, gateway, command):
    deadline = time.monotonic() + 15
    if gateway(checked, deadline, original=True)["dropins"]:
        raise ValueError("gateway already has drop-ins; inspect its actual deployment")
    for path in (
        plan.GATEWAY_DROPIN,
        plan.BRIDGE_UNIT,
        plan.BRIDGE_CONFIG,
        plan.CAPABILITY,
    ):
        if path.exists() or path.is_symlink():
            raise ValueError(
                "chat deployment path already exists; reconcile its original installation"
            )
    if (
        io.digest(io.read_public(plan.POLICY))
        != checked["request"]["original_policy_sha256"]
        or io.digest(io.read_public(plan.GATEWAY_UNIT))
        != checked["request"]["original_gateway_unit_sha256"]
    ):
        raise ValueError("original configuration changed before preparation")
    keyring_available(deadline, command)
    source_access(checked, deadline, command)
    namespace = checked["namespace"]
    io.protected_parents(plan.INSTALL_ROOT)
    plan.INSTALL_ROOT.mkdir(mode=0o700, exist_ok=True)
    root_info = plan.INSTALL_ROOT.lstat()
    if (
        root_info.st_uid != 0
        or root_info.st_mode & 0o077
        or not plan.INSTALL_ROOT.is_dir()
    ):
        raise ValueError("external installation root is not Root-private")
    io.protected_parents(namespace)
    namespace.mkdir(mode=0o700)  # O_EXCL directory: this installation is single-use.
    io.barrier(namespace.parent)
    io.durable_create(namespace / "request.json", checked["request_bytes"])
    io.durable_create(namespace / "original-desktop.json", checked["desktop_bytes"])
    io.durable_create(
        namespace / "original-gateway.service", io.read_public(plan.GATEWAY_UNIT)
    )
    io.durable_create(
        namespace / "original-host-policy.json", io.read_public(plan.POLICY)
    )
    io.durable_create(
        namespace / "candidate-host-policy.json", checked["target_policy"]
    )
    io.log(
        namespace,
        "prepared",
        original_gateway=gateway(checked, deadline, original=True),
        target_policy_sha256=checked["target_policy_sha256"],
    )
    account = "hepta-chat-" + secrets.token_hex(16)
    token = bytearray(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"="))
    try:
        io.durable_create(namespace / "chat.capability", token, mode=0o440, gid=973)
        io.durable_create(
            namespace / "account.json",
            io.encode({"account": account, "token_digest": io.digest(token)}),
        )
        io.log(namespace, "keyring-import-started", account=account)
        user = pwd.getpwuid(1000)
        command(
            [
                "/usr/sbin/runuser",
                "-u",
                user.pw_name,
                "--",
                "/usr/bin/env",
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                "XDG_RUNTIME_DIR=/run/user/1000",
                checked["request"]["credential_helper"]["path"],
                "import-chat",
                account,
            ],
            time.monotonic() + 15,
            token,
        )
        io.log(namespace, "keyring-paired", account=account)
    except Exception as error:
        io.log(
            namespace,
            "keyring-outcome-unresolved",
            account=account,
            child_pid=getattr(error, "child_pid", None),
        )
        raise
    finally:
        token[:] = b"\0" * len(token)
    return {
        "namespace": str(namespace),
        "target_policy_sha256": checked["target_policy_sha256"],
        "next": "Root must perform its original Owner handoff with candidate-host-policy.json; then activate with the actual new epoch. No Fleet/Agent changes were performed.",
    }
