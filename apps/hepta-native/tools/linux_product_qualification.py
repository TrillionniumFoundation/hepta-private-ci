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
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=kwargs.pop("timeout", 20), **kwargs)


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


def provision_isolated_owner_fixture(root: Path) -> dict[str, str]:
    """Mirror the runtime owner's independent fixture, not an app writer API."""
    root.mkdir(mode=0o700)
    runtime = root / "runtime-v2"
    runtime.mkdir(mode=0o700)
    keys = runtime / "keys"
    keys.mkdir(mode=0o700)
    material = {}
    for name in ["runtime-integrity.key", "preference-integrity.key", "preference-ingress-auth.key"]:
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
    for name, key_name in [("outcomes.sqlite3", "runtime-integrity.key"), ("preferences.sqlite3", "preference-integrity.key")]:
        key = material[key_name]
        with sqlite3.connect(runtime / name) as db:
            db.execute("CREATE TABLE hepta_v2_schema(singleton INTEGER PRIMARY KEY,version INTEGER NOT NULL)")
            db.execute("CREATE TABLE hepta_v2_write_lock(singleton INTEGER PRIMARY KEY,generation INTEGER NOT NULL)")
            db.execute("CREATE TABLE hepta_v2_integrity(singleton INTEGER PRIMARY KEY,algorithm TEXT NOT NULL,key_id TEXT NOT NULL)")
            db.execute("INSERT INTO hepta_v2_schema VALUES(1,5)")
            db.execute("INSERT INTO hepta_v2_write_lock VALUES(1,0)")
            key_id = "sha256:" + hashlib.sha256(frame(b"hepta.memory.durable-integrity.key-id.v1") + frame(key)).hexdigest()
            db.execute("INSERT INTO hepta_v2_integrity VALUES(1,?,?)", ("hmac-sha256-v1", key_id))
            for table, columns in row_tables.items():
                db.execute(f"CREATE TABLE {table}({columns},payload_json TEXT NOT NULL,storage_hash TEXT NOT NULL)")
        os.chmod(runtime / name, 0o600)
        digests[name] = hashlib.sha256((runtime / name).read_bytes()).hexdigest()
    payload = b'{"version":1,"generation":0,"snapshot":{"sessions":[],"memories":[],"transcripts":[]}}'
    envelope = b'{"payload":' + payload + b',"integrity_tag":' + json.dumps(row_mac(material["runtime-integrity.key"], payload)).encode() + b'}'
    private_write(runtime / "runtime-state.json", envelope)
    digests["runtime-state.json"] = hashlib.sha256(envelope).hexdigest()
    return digests


def write_endpoint(root: Path, account: str, address: str):
    signing = Ed25519PrivateKey.generate()
    public = signing.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    now = int(time.time() * 1000)
    manifest = dict(schema="hepta.endpoint-manifest.v1", endpoint_id="qualification.native", address=address,
                    protocol_version=2, gateway_credential_account=account, issued_unix_ms=now-1000,
                    expires_unix_ms=now+600_000, key_id="qualification.endpoint")
    message = "hepta.endpoint-manifest-payload.v1\n" + "".join(f"{key}={value}\n" for key, value in manifest.items())
    manifest["manifest_digest"] = hashlib.sha256(message.encode()).hexdigest()
    signature = "hepta.endpoint-manifest-signature.v1\nmanifest_digest=" + manifest["manifest_digest"] + "\n"
    manifest["signature_base64"] = base64.b64encode(signing.sign(signature.encode())).decode()
    private_write(root / "endpoint.json", json.dumps(manifest).encode())
    private_write(root / "trusted-keys.json", json.dumps({"schema":"hepta.native-trusted-keys.v1", "keys":{"qualification.endpoint":base64.b64encode(public).decode()}}).encode())
    return signing


def close_native_window(window_id: str) -> None:
    """Request normal close via WM_DELETE_WINDOW, even without a window manager.

    xdotool windowclose destroys the server resource, which is not the same
    lifecycle event as a user requesting that an application close its window.
    """
    library = ctypes.util.find_library("X11")
    if library is None:
        raise RuntimeError("libX11 is required for native lifecycle qualification")
    x11 = ctypes.CDLL(library)
    class Data(ctypes.Union):
        _fields_ = [("bytes", ctypes.c_char * 20), ("shorts", ctypes.c_short * 10),
                    ("longs", ctypes.c_long * 5)]
    class ClientMessage(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                    ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                    ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                    ("format", ctypes.c_int), ("data", Data)]
    class Event(ctypes.Union):
        _fields_ = [("client", ClientMessage), ("padding", ctypes.c_long * 24)]
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                              ctypes.c_long, ctypes.POINTER(Event)]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("could not connect to the isolated X display")
    try:
        event = Event()
        event.client.type = 33  # ClientMessage
        event.client.send_event = 1
        event.client.display = display
        event.client.window = int(window_id)
        event.client.message_type = x11.XInternAtom(display, b"WM_PROTOCOLS", 0)
        event.client.format = 32
        event.client.data.longs[0] = x11.XInternAtom(display, b"WM_DELETE_WINDOW", 0)
        event.client.data.longs[1] = 0  # CurrentTime
        if x11.XSendEvent(display, int(window_id), 0, 0, ctypes.byref(event)) == 0:
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
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"product exited before readiness, code={process.returncode}; inspect logs")
        if path.exists():
            value=json.loads(path.read_text())
            if value.get("process_id") == process.pid:
                return value
        time.sleep(.05)
    raise TimeoutError("normal GUI did not emit a startup observation")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--package-root",type=Path,required=True)
    parser.add_argument("--gateway",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    args=parser.parse_args()
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        parser.error("run in an isolated Xvfb and dbus-run-session")
    out=args.out_dir.resolve()
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    home=out/"isolated-home";home.mkdir(mode=0o700)
    runtime_dir=out/"session-runtime";runtime_dir.mkdir(mode=0o700)
    environment=dict(os.environ, HOME=str(home),XDG_CONFIG_HOME=str(home/".config"),XDG_DATA_HOME=str(home/".local/share"),XDG_RUNTIME_DIR=str(runtime_dir),LANG="C.UTF-8",LC_ALL="C.UTF-8")
    root=args.package_root.resolve()
    package=json.loads((root/"unsigned-package-manifest.json").read_text())
    for relative, expected in package["binarySha256"].items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=expected:
            raise RuntimeError("installed package binary does not match its retained digest")
    app=root/"usr/bin/hepta-native";credential=root/"usr/bin/hepta-native-credential"
    if not app.is_file(): parser.error("Linux AppDir package required")
    owner=out/"owner-fixture";before=provision_isolated_owner_fixture(owner)
    account="native.qual."+secrets.token_hex(12)
    gateway_process=keyring_process=gui=None
    try:
        with (out/"keyring.log").open("w") as log:
            keyring_process=subprocess.Popen(["gnome-keyring-daemon","--foreground","--unlock","--components=secrets","--control-directory",str(runtime_dir/"keyring")],env=environment,stdin=subprocess.PIPE,stdout=log,stderr=log)
            keyring_process.stdin.write(secrets.token_hex(24).encode()+b"\n")
            keyring_process.stdin.close()
        time.sleep(.5)
        provision=json.loads(run([str(credential),"provision",account],env=environment).stdout)
        # The helper reports only an account and digest. Never fetch the secret.
        if "token" in provision: raise RuntimeError("credential provisioning exposed a secret")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1",0));port=reservation.getsockname()[1]
        address=f"127.0.0.1:{port}"
        write_endpoint(out,account,address)
        state=out/"shell-state"
        config={"endpoint_manifest":str(out/"endpoint.json"),"trusted_keys":str(out/"trusted-keys.json"),"state_dir":str(state)}
        private_write(out/"config.json",json.dumps(config).encode())
        with (out/"gateway.log").open("w") as log:
            gateway_process=subprocess.Popen([str(args.gateway.resolve()),"--listen",address,"--state-root",str(owner),"--auth-keyring-account",account],env=environment,stdout=log,stderr=log)
        deadline=time.monotonic()+20
        while True:
            if gateway_process.poll() is not None: raise RuntimeError("real gateway bootstrap failed; inspect gateway.log")
            try:
                with socket.create_connection(("127.0.0.1",port),timeout=.1):break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        connection=json.loads(run([str(app),"--config",str(out/"config.json"),"--check-connection"],env=environment).stdout)
        starts=[]
        for iteration in range(2):
            with (out/f"gui-{iteration}.log").open("w") as log:
                gui=subprocess.Popen([str(app),"--config",str(out/"config.json")],env=environment,stdout=log,stderr=log)
            startup=await_json(state/"last-startup.json",gui)
            if startup["session"]["session_id"]==connection["session"]["session_id"]:raise AssertionError("reused a prior session")
            windows=run(["xdotool","search","--sync","--onlyvisible","--pid",str(gui.pid)],env=environment).stdout.split()
            if not windows:raise AssertionError("normal product created no visible native window")
            window=windows[0]
            run(["xdotool","key","--window",window,"Tab","Tab","Shift+Tab"],env=environment)
            geometry=run(["xwininfo","-id",window],env=environment).stdout
            (out/f"window-{iteration}.txt").write_text(geometry)
            time.sleep(.25)
            if gui.poll() is not None:raise AssertionError("normal GUI exited during keyboard traversal")
            # WM_DELETE_WINDOW, not a test-profile exit flag.
            close_native_window(window)
            exit_code = gui.wait(timeout=10)
            if exit_code != 0:
                raise RuntimeError(f"normal GUI close failed with exit code {exit_code}; inspect gui-{iteration}.log")
            startup["normal_close_exit_code"] = exit_code
            starts.append(startup)
            gui=None
        if starts[0]["session"]["session_id"]==starts[1]["session"]["session_id"]:raise AssertionError("restart reused session identity")
        after={name:hashlib.sha256((owner/"runtime-v2"/name).read_bytes()).hexdigest() for name in before}
        if before!=after:raise AssertionError("read-only product path mutated owner state")
        receipt={"schema":"hepta.native-linux-product-qualification.v1","packageBinarySha256":package["binarySha256"],"gatewaySha256":hashlib.sha256(args.gateway.read_bytes()).hexdigest(),"normalConnection":connection,"ordinaryGuiStarts":starts,"visibleWindowObserved":True,"keyboardEventsDelivered":True,"normalCloseVerified":True,"ownerStateUnchanged":True,"environment":"isolated Linux Xvfb/DBus with real OS keyring and owner-format fixture", "physicalDisplayAcceptance":False,"screenReaderAcceptance":False,"independentAcceptance":False,"release":False}
        (out/"product-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt,indent=2))
    finally:
        terminate(gui);terminate(gateway_process)
        try:run([str(credential),"delete",account],env=environment,timeout=10)
        except Exception:pass
        terminate(keyring_process)
        # Ephemeral keys and database rows are qualification-only private inputs.
        # Preserve public evidence/logs, not secret key material in deliverables.
        shutil.rmtree(home,ignore_errors=True)
        shutil.rmtree(owner,ignore_errors=True)


if __name__=="__main__":main()
