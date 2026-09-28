#!/usr/bin/env python3
"""Exercise installed native binaries via real Linux gateway/keyring/GUI paths.

Run only inside a fresh dbus-run-session + Xvfb session. This creates an isolated
owner-format schema-v5 database fixture, never a production state initializer.
No live effect authority, signing credentials, or existing keyring are consumed.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def run(command, **kwargs):
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 20),
        **kwargs,
    )


def frame(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def row_mac(key: bytes, payload: bytes) -> str:
    message = frame(b"hepta.memory.durable-integrity.row-mac.v1") + frame(payload)
    return "hmac-sha256:" + hmac.new(key, message, hashlib.sha256).hexdigest()


def private_write(path: Path, value: bytes) -> None:
    with path.open("xb") as target:
        os.chmod(path, 0o600)
        target.write(value)
        target.flush()
        os.fsync(target.fileno())


def required_environment() -> dict[str, str]:
    names = (
        "CANDIDATE",
        "NATIVE_EXPECTED_HEAD",
        "KIND",
        "WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "ImageOS",
        "ImageVersion",
        "RUNNER_ARCH",
    )
    values = {name: os.environ.get(name, "") for name in names}
    if any(not value for value in values.values()):
        raise RuntimeError("exact-source CI identity or runner image is missing")
    for name in ("CANDIDATE", "NATIVE_EXPECTED_HEAD", "WORKFLOW_SHA"):
        if not SHA.fullmatch(values[name]) or values[name] == "0" * 40:
            raise RuntimeError(f"{name} must be a complete nonzero commit identity")
    if values["KIND"] not in {"head", "merge"}:
        raise RuntimeError("KIND must be head or merge")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not values[name].isdigit() or int(values[name]) <= 0:
            raise RuntimeError(f"{name} must be a positive CI identity")
    observed_head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if observed_head != values["NATIVE_EXPECTED_HEAD"]:
        raise RuntimeError("installed-product checkout differs from expected source")
    source_tree = run(["git", "rev-parse", "HEAD^{tree}"]).stdout.strip()
    if not SHA.fullmatch(source_tree):
        raise RuntimeError("installed-product source tree identity is invalid")
    values["SOURCE_TREE_SHA"] = source_tree
    return values


def provision_isolated_owner_fixture(root: Path) -> dict[str, str]:
    """Mirror the runtime owner's independent fixture, not an app writer API."""
    root.mkdir(mode=0o700)
    runtime = root / "runtime-v2"
    runtime.mkdir(mode=0o700)
    keys = runtime / "keys"
    keys.mkdir(mode=0o700)
    material = {}
    for name in [
        "runtime-integrity.key",
        "preference-integrity.key",
        "preference-ingress-auth.key",
    ]:
        material[name] = secrets.token_bytes(32)
        private_write(keys / name, material[name].hex().encode() + b"\n")
    row_tables = {
        "hepta_v2_outcome_records": "receipt_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL",
        "hepta_v2_outcome_intents": "attempt_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, state TEXT NOT NULL",
        "hepta_v2_execution_intents": "attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL",
        "hepta_v2_execution_effect_acks": "attempt_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL, effect_plan_hash TEXT NOT NULL",
        "hepta_v2_preference_genesis": "preference_id TEXT NOT NULL, subject_id TEXT NOT NULL",
        "hepta_v2_preference_heads": "preference_id TEXT NOT NULL, subject_id TEXT NOT NULL",
        "hepta_v2_preference_transitions": "sequence INTEGER PRIMARY KEY, transition_id TEXT NOT NULL, evidence_id TEXT NOT NULL, receipt_id TEXT NOT NULL, preference_id TEXT NOT NULL, subject_id TEXT NOT NULL",
    }
    digests = {}
    for name, key_name in [
        ("outcomes.sqlite3", "runtime-integrity.key"),
        ("preferences.sqlite3", "preference-integrity.key"),
    ]:
        key = material[key_name]
        with sqlite3.connect(runtime / name) as db:
            db.execute(
                "CREATE TABLE hepta_v2_schema(singleton INTEGER PRIMARY KEY,version INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE hepta_v2_write_lock(singleton INTEGER PRIMARY KEY,generation INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE hepta_v2_integrity(singleton INTEGER PRIMARY KEY,algorithm TEXT NOT NULL,key_id TEXT NOT NULL)"
            )
            db.execute("INSERT INTO hepta_v2_schema VALUES(1,5)")
            db.execute("INSERT INTO hepta_v2_write_lock VALUES(1,0)")
            key_id = "sha256:" + hashlib.sha256(
                frame(b"hepta.memory.durable-integrity.key-id.v1") + frame(key)
            ).hexdigest()
            db.execute(
                "INSERT INTO hepta_v2_integrity VALUES(1,?,?)",
                ("hmac-sha256-v1", key_id),
            )
            for table, columns in row_tables.items():
                db.execute(
                    f"CREATE TABLE {table}({columns},payload_json TEXT NOT NULL,storage_hash TEXT NOT NULL)"
                )
        os.chmod(runtime / name, 0o600)
        digests[name] = hashlib.sha256((runtime / name).read_bytes()).hexdigest()
    payload = b'{"version":1,"generation":0,"snapshot":{"sessions":[],"memories":[],"transcripts":[]}}'
    envelope = (
        b'{"payload":'
        + payload
        + b',"integrity_tag":'
        + json.dumps(row_mac(material["runtime-integrity.key"], payload)).encode()
        + b"}"
    )
    private_write(runtime / "runtime-state.json", envelope)
    digests["runtime-state.json"] = hashlib.sha256(envelope).hexdigest()
    return digests


def write_endpoint(root: Path, account: str, address: str):
    signing = Ed25519PrivateKey.generate()
    public = signing.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    now = int(time.time() * 1000)
    manifest = dict(
        schema="hepta.endpoint-manifest.v1",
        endpoint_id="qualification.native",
        address=address,
        protocol_version=2,
        gateway_credential_account=account,
        issued_unix_ms=now - 1000,
        expires_unix_ms=now + 600_000,
        key_id="qualification.endpoint",
    )
    message = "hepta.endpoint-manifest-payload.v1\n" + "".join(
        f"{key}={value}\n" for key, value in manifest.items()
    )
    manifest["manifest_digest"] = hashlib.sha256(message.encode()).hexdigest()
    signature = (
        "hepta.endpoint-manifest-signature.v1\nmanifest_digest="
        + manifest["manifest_digest"]
        + "\n"
    )
    manifest["signature_base64"] = base64.b64encode(
        signing.sign(signature.encode())
    ).decode()
    private_write(root / "endpoint.json", json.dumps(manifest).encode())
    private_write(
        root / "trusted-keys.json",
        json.dumps(
            {
                "schema": "hepta.native-trusted-keys.v1",
                "keys": {
                    "qualification.endpoint": base64.b64encode(public).decode()
                },
            }
        ).encode(),
    )
    return signing


def close_native_window(window_id: str) -> None:
    """Request normal close via WM_DELETE_WINDOW, even without a window manager."""
    library = ctypes.util.find_library("X11")
    if library is None:
        raise RuntimeError("libX11 is required for native lifecycle qualification")
    x11 = ctypes.CDLL(library)

    class Data(ctypes.Union):
        _fields_ = [
            ("bytes", ctypes.c_char * 20),
            ("shorts", ctypes.c_short * 10),
            ("longs", ctypes.c_long * 5),
        ]

    class ClientMessage(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", ctypes.c_void_p),
            ("window", ctypes.c_ulong),
            ("message_type", ctypes.c_ulong),
            ("format", ctypes.c_int),
            ("data", Data),
        ]

    class Event(ctypes.Union):
        _fields_ = [("client", ClientMessage), ("padding", ctypes.c_long * 24)]

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_long,
        ctypes.POINTER(Event),
    ]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("could not connect to the isolated X display")
    try:
        event = Event()
        event.client.type = 33
        event.client.send_event = 1
        event.client.display = display
        event.client.window = int(window_id)
        event.client.message_type = x11.XInternAtom(display, b"WM_PROTOCOLS", 0)
        event.client.format = 32
        event.client.data.longs[0] = x11.XInternAtom(
            display, b"WM_DELETE_WINDOW", 0
        )
        event.client.data.longs[1] = 0
        if (
            x11.XSendEvent(display, int(window_id), 0, 0, ctypes.byref(event))
            == 0
        ):
            raise RuntimeError("WM_DELETE_WINDOW could not be delivered")
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


def terminate(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def await_json(path, process, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"product exited before readiness, code={process.returncode}; inspect logs"
            )
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("process_id") == process.pid:
                return value
        time.sleep(0.05)
    raise TimeoutError("normal GUI did not emit a startup observation")


def validate_provision_receipt(value: dict, account: str) -> None:
    if set(value) != {"schema", "account", "token_digest"}:
        raise RuntimeError("credential provisioning receipt has unexpected fields")
    if (
        value["schema"] != "hepta.native-gateway-credential-provision.v1"
        or value["account"] != account
        or not isinstance(value["token_digest"], str)
        or not DIGEST.fullmatch(value["token_digest"])
    ):
        raise RuntimeError("credential provisioning receipt is invalid")


def validate_delete_receipt(value: dict, account: str) -> None:
    if set(value) != {"schema", "account", "deleted"}:
        raise RuntimeError("credential deletion receipt has unexpected fields")
    if (
        value["schema"] != "hepta.native-gateway-credential-delete.v1"
        or value["account"] != account
        or value["deleted"] is not True
    ):
        raise RuntimeError("credential deletion was not observed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--gateway", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    identity = required_environment()
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        parser.error("run in an isolated Xvfb and dbus-run-session")
    out = args.out_dir.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = out / "isolated-home"
    home.mkdir(mode=0o700)
    runtime_dir = out / "session-runtime"
    runtime_dir.mkdir(mode=0o700)
    environment = dict(
        os.environ,
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local/share"),
        XDG_RUNTIME_DIR=str(runtime_dir),
        LANG="C.UTF-8",
        LC_ALL="C.UTF-8",
    )
    root = args.package_root.resolve()
    package_manifest_path = root / "unsigned-package-manifest.json"
    package = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    for relative, expected in package["binarySha256"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError("installed package binary does not match its retained digest")
    app = root / "usr/bin/hepta-native"
    credential = root / "usr/bin/hepta-native-credential"
    if not app.is_file():
        parser.error("Linux AppDir package required")
    owner = out / "owner-fixture"
    before = provision_isolated_owner_fixture(owner)
    account = "native.qual." + secrets.token_hex(12)
    gateway_process = keyring_process = gui = None
    credential_deleted = False
    try:
        with (out / "keyring.log").open("w") as log:
            keyring_process = subprocess.Popen(
                [
                    "gnome-keyring-daemon",
                    "--foreground",
                    "--unlock",
                    "--components=secrets",
                    "--control-directory",
                    str(runtime_dir / "keyring"),
                ],
                env=environment,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
            )
            keyring_process.stdin.write(secrets.token_hex(24).encode() + b"\n")
            keyring_process.stdin.close()
        time.sleep(0.5)
        provision = json.loads(
            run([str(credential), "provision", account], env=environment).stdout
        )
        validate_provision_receipt(provision, account)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        address = f"127.0.0.1:{port}"
        write_endpoint(out, account, address)
        state = out / "shell-state"
        config = {
            "endpoint_manifest": str(out / "endpoint.json"),
            "trusted_keys": str(out / "trusted-keys.json"),
            "state_dir": str(state),
        }
        private_write(out / "config.json", json.dumps(config).encode())
        with (out / "gateway.log").open("w") as log:
            gateway_process = subprocess.Popen(
                [
                    str(args.gateway.resolve()),
                    "--listen",
                    address,
                    "--state-root",
                    str(owner),
                    "--auth-keyring-account",
                    account,
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
        deadline = time.monotonic() + 20
        while True:
            if gateway_process.poll() is not None:
                raise RuntimeError("real gateway bootstrap failed; inspect gateway.log")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        connection = json.loads(
            run(
                [str(app), "--config", str(out / "config.json"), "--check-connection"],
                env=environment,
            ).stdout
        )
        starts = []
        for iteration in range(2):
            launch_started = time.perf_counter_ns()
            with (out / f"gui-{iteration}.log").open("w") as log:
                gui = subprocess.Popen(
                    [str(app), "--config", str(out / "config.json")],
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
            startup = await_json(state / "last-startup.json", gui)
            readiness_observed = time.perf_counter_ns()
            if startup["session"]["session_id"] == connection["session"]["session_id"]:
                raise AssertionError("reused a prior session")
            windows = run(
                [
                    "xdotool",
                    "search",
                    "--sync",
                    "--onlyvisible",
                    "--pid",
                    str(gui.pid),
                ],
                env=environment,
            ).stdout.split()
            if not windows:
                raise AssertionError("normal product created no visible native window")
            visible_observed = time.perf_counter_ns()
            window = windows[0]
            run(["xdotool", "windowfocus", "--sync", window], env=environment)
            focus_before = int(
                run(["xdotool", "getwindowfocus", "-f"], env=environment).stdout.strip()
            )
            if focus_before != int(window):
                raise AssertionError("native window did not receive virtual display focus")
            keyboard_started = time.perf_counter_ns()
            run(
                [
                    "xdotool",
                    "key",
                    "--window",
                    window,
                    "Tab",
                    "Tab",
                    "Shift+Tab",
                ],
                env=environment,
            )
            keyboard_finished = time.perf_counter_ns()
            focus_after = int(
                run(["xdotool", "getwindowfocus", "-f"], env=environment).stdout.strip()
            )
            if focus_after != int(window):
                raise AssertionError("keyboard traversal lost the native top-level focus")
            geometry = run(["xwininfo", "-id", window], env=environment).stdout
            (out / f"window-{iteration}.txt").write_text(geometry, encoding="utf-8")
            time.sleep(0.25)
            if gui.poll() is not None:
                raise AssertionError("normal GUI exited during keyboard traversal")
            status_fields = Path(f"/proc/{gui.pid}/status").read_text(encoding="utf-8")
            rss_lines = [
                line for line in status_fields.splitlines() if line.startswith("VmRSS:")
            ]
            rss_kib = int(rss_lines[0].split()[1]) if rss_lines else None
            close_started = time.perf_counter_ns()
            close_native_window(window)
            exit_code = gui.wait(timeout=10)
            if exit_code != 0:
                raise RuntimeError(
                    f"normal GUI close failed with exit code {exit_code}; inspect gui-{iteration}.log"
                )
            startup["normal_close_exit_code"] = exit_code
            startup["measurements"] = {
                "schema": "hepta.native.ordinary-linux-measurement.v2",
                "packageBinarySha256": package["binarySha256"],
                "launchToReadinessMs": (
                    readiness_observed - launch_started
                )
                / 1_000_000,
                "launchToVisibleWindowMs": (
                    visible_observed - launch_started
                )
                / 1_000_000,
                "keyboardCommandMs": (
                    keyboard_finished - keyboard_started
                )
                / 1_000_000,
                "normalCloseMs": (
                    time.perf_counter_ns() - close_started
                )
                / 1_000_000,
                "residentKiBAtObservation": rss_kib,
                "focusedWindowBefore": focus_before,
                "focusedWindowAfter": focus_after,
                "sampleIndex": iteration,
                "virtualFocusObserved": True,
                "keyboardEventsDelivered": True,
                "inputLatencyMeasured": False,
                "soakMeasured": False,
                "productionThresholdEvaluated": False,
            }
            starts.append(startup)
            gui = None
        if starts[0]["session"]["session_id"] == starts[1]["session"]["session_id"]:
            raise AssertionError("restart reused session identity")
        after = {
            name: hashlib.sha256((owner / "runtime-v2" / name).read_bytes()).hexdigest()
            for name in before
        }
        if before != after:
            raise AssertionError("read-only product path mutated owner state")
        terminate(gateway_process)
        gateway_process = None
        deletion = json.loads(
            run([str(credential), "delete", account], env=environment, timeout=10).stdout
        )
        validate_delete_receipt(deletion, account)
        credential_deleted = True
        receipt = {
            "schema": "hepta.native-linux-product-qualification.v2",
            "candidateSha": identity["CANDIDATE"],
            "sourceSha": identity["NATIVE_EXPECTED_HEAD"],
            "sourceTreeSha": identity["SOURCE_TREE_SHA"],
            "sourceKind": identity["KIND"],
            "workflowSha": identity["WORKFLOW_SHA"],
            "runId": identity["GITHUB_RUN_ID"],
            "runAttempt": identity["GITHUB_RUN_ATTEMPT"],
            "runner": {
                "ImageOS": identity["ImageOS"],
                "ImageVersion": identity["ImageVersion"],
                "RUNNER_ARCH": identity["RUNNER_ARCH"],
            },
            "packageBinarySha256": package["binarySha256"],
            "packageManifestSha256": hashlib.sha256(
                package_manifest_path.read_bytes()
            ).hexdigest(),
            "gatewaySha256": hashlib.sha256(args.gateway.read_bytes()).hexdigest(),
            "keyringProvisionReceipt": provision,
            "keyringDeleteReceipt": deletion,
            "keyringCredentialLifecycleObserved": True,
            "normalConnection": connection,
            "ordinaryGuiStarts": starts,
            "visibleWindowObserved": True,
            "virtualFocusObserved": True,
            "keyboardEventsDelivered": True,
            "normalCloseVerified": True,
            "ownerStateUnchanged": True,
            "environment": "isolated Linux Xvfb/DBus with real OS keyring and owner-format fixture",
            "physicalDisplayAcceptance": False,
            "physicalInputAcceptance": False,
            "screenReaderAcceptance": False,
            "cjkImeAcceptance": False,
            "independentAcceptance": False,
            "productionKeyCustodyAcceptance": False,
            "release": False,
        }
        (out / "product-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(receipt, indent=2))
    finally:
        terminate(gui)
        terminate(gateway_process)
        if not credential_deleted:
            try:
                run([str(credential), "delete", account], env=environment, timeout=10)
            except Exception:
                pass
        terminate(keyring_process)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(owner, ignore_errors=True)


if __name__ == "__main__":
    main()
