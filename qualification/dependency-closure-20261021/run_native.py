#!/usr/bin/env python3
"""Exercise real credential storage on a private bus with disposable test data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gnome-prefix", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-tokio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inside-session", action="store_true")
    args = parser.parse_args()
    if not args.inside_session:
        return subprocess.call(
            ["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
             *sys.argv[1:], "--inside-session"]
        )

    args.output.mkdir(parents=True, exist_ok=True)
    receipts = []
    binaries = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
        "candidate_tokio": args.candidate_tokio.resolve(),
    }
    binary_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in binaries.items()
    }
    daemon = None
    daemon_log = (args.output / "gnome-keyring.log").open("wb")
    with tempfile.TemporaryDirectory(prefix="hepta-native-keyring-") as temporary:
        fixture = Path(temporary)
        env = os.environ.copy()
        # Keep the user's HOME and session untouched. All GNOME data/control
        # paths belong to this private bus and disposable test directory.
        for variable, relative in (
            ("XDG_DATA_HOME", "data"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_RUNTIME_DIR", "runtime"),
            ("GNOME_KEYRING_CONTROL", "control"),
        ):
            path = fixture / relative
            path.mkdir(mode=0o700)
            env[variable] = str(path)
        env["LD_LIBRARY_PATH"] = str(args.gnome_prefix / "usr/lib/x86_64-linux-gnu")
        # Session buses need no user display for this explicitly unlocked fixture.
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)

        def has_owner():
            result = subprocess.run(
                ["dbus-send", "--session", "--print-reply", "--type=method_call",
                 "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                 "org.freedesktop.DBus.NameHasOwner", "string:org.freedesktop.secrets"],
                env=env, capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and "boolean true" in result.stdout

        def start_daemon():
            nonlocal daemon
            if has_owner():
                raise RuntimeError("private bus unexpectedly already has a Secret Service")
            daemon = subprocess.Popen(
                [str(args.gnome_prefix / "usr/bin/gnome-keyring-daemon"),
                 "--foreground", "--components=secrets", "--unlock",
                 "--control-directory=" + env["GNOME_KEYRING_CONTROL"]],
                env=env, stdin=subprocess.PIPE, stdout=daemon_log, stderr=daemon_log,
            )
            daemon.stdin.write(b"synthetic-qualification-keyring-passphrase\n")
            daemon.stdin.close()
            for _ in range(100):
                if daemon.poll() is not None:
                    raise RuntimeError("isolated GNOME Keyring daemon exited")
                if has_owner():
                    return
                time.sleep(0.05)
            raise RuntimeError("isolated Secret Service readiness timed out")

        def stop_daemon():
            nonlocal daemon
            if daemon is not None:
                daemon.terminate()
                daemon.wait(timeout=10)
                daemon = None
            for _ in range(100):
                if not has_owner():
                    return
                time.sleep(0.05)
            raise RuntimeError("private Secret Service did not release its bus name")

        def run(which, mode, phase, service, unavailable=False):
            command = [str(binaries[which]), mode, phase, service]
            case_env = env.copy()
            if unavailable:
                case_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(fixture / "absent-bus")
            started = time.monotonic()
            result = subprocess.run(
                command, env=case_env, capture_output=True, text=True, timeout=40
            )
            receipt = {
                "binary": which, "runtime": mode, "phase": phase,
                "service": service, "exit_code": result.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stdout": result.stdout, "stderr": result.stderr,
            }
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
            if result.returncode:
                raise RuntimeError(f"native credential case failed: {which}/{mode}/{phase}")

        status = "failed"
        try:
            start_daemon()
            service = "hepta-dependency-cross-version"
            run("baseline", "sync", "seed", service)
            run("candidate", "sync", "update", service)
            run("baseline", "sync", "verify", service)
            run("candidate", "sync", "verify", service)
            run("candidate_tokio", "current-thread", "verify", service)
            run("candidate", "sync", "delete", service)
            run("baseline", "sync", "absent", service)

            # Data survives a complete service restart under a password-protected
            # keyring. Inspect bytes only for our known synthetic fixture values.
            stop_daemon()
            keyring_files = list((fixture / "data/keyrings").glob("*.keyring"))
            if not keyring_files:
                raise RuntimeError("no persistent keyring file was created")
            for path in keyring_files:
                data = path.read_bytes()
                for secret in (
                    b"synthetic-dependency-first-62a57266",
                    "synthetic-dependency-updated-🔐-82f584bf".encode(),
                    b"synthetic-persistent-f73e6dfd",
                ):
                    if secret in data:
                        raise RuntimeError("synthetic secret was found in plaintext on disk")
            receipts.append({"persistent_files": len(keyring_files), "synthetic_plaintext_found": False})
            start_daemon()
            run("candidate", "sync", "persistent", service)
            run("baseline", "sync", "persistent", service)
            run("candidate", "sync", "finish", service)

            for which in ("candidate", "candidate_tokio"):
                for mode in ("sync", "current-thread", "multi-thread", "spawn-blocking"):
                    run(which, mode, "round-trip", f"hepta-runtime-{which}-{mode}")
                run(which, "sync", "concurrent", f"hepta-concurrent-{which}")
                run(which, "current-thread", "unavailable", f"hepta-unavailable-{which}", unavailable=True)
            run("baseline", "sync", "unavailable", "hepta-unavailable-baseline", unavailable=True)
            status = "passed"
        finally:
            stop_daemon()
            daemon_log.close()
            (args.output / "native-results.json").write_text(
                json.dumps({"status": status, "binary_sha256": binary_hashes,
                            "isolated_dbus": True, "cases": receipts}, indent=2) + "\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
