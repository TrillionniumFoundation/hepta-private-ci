"""Replay old/new exact-wrapper binaries against an isolated real Secret Service."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time


ALGORITHM = "dh-ietf1024-sha256-aes128-cbc-pkcs7"


def line_with_deadline(process, timeout=15):
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        assert selector.select(timeout), "child readiness timeout"
        line = process.stdout.readline().strip()
        assert line, "child exited before readiness"
        return line
    finally:
        selector.close()


def stop(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--gnome-keyring", type=Path, required=True)
    parser.add_argument("--system-python", type=Path, default=Path("/usr/bin/python3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    inputs = json.loads(args.inputs.read_text())
    for path, expected in inputs.items():
        assert hashlib.sha256((repo / path).read_bytes()).hexdigest() == expected
    args.output.mkdir(parents=True, exist_ok=False)
    binaries = {"baseline": args.baseline, "candidate": args.candidate}
    receipt = {
        "binaries": {
            k: {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for k, p in binaries.items()
        },
        "steps": [],
        "status": "RUNNING",
    }
    processes = []
    files = []
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-private-keyring-") as directory:
            private = Path(directory)
            (private / "control").mkdir(mode=0o700)
            env = os.environ.copy()
            for key in [
                "XDG_RUNTIME_DIR",
                "XDG_DATA_HOME",
                "XDG_CONFIG_HOME",
                "XDG_CACHE_HOME",
            ]:
                path = private / key.lower()
                path.mkdir(mode=0o700)
                env[key] = str(path)
            env.pop("GNOME_KEYRING_CONTROL", None)
            env.pop("DBUS_STARTER_ADDRESS", None)
            env.pop("DBUS_STARTER_BUS_TYPE", None)
            buslog = (args.output / "bus.log").open("w")
            files.append(buslog)
            bus_socket = Path(env["XDG_RUNTIME_DIR"]) / "bus"
            bus = subprocess.Popen(
                [
                    "dbus-daemon",
                    "--session",
                    "--nofork",
                    "--print-address=1",
                    f"--address=unix:path={bus_socket}",
                ],
                stdout=subprocess.PIPE,
                stderr=buslog,
                text=True,
                env=env,
            )
            processes.append(bus)
            env["DBUS_SESSION_BUS_ADDRESS"] = line_with_deadline(bus)
            monitorlog = (args.output / "session-monitor.log").open("w")
            files.append(monitorlog)
            monitor = subprocess.Popen(
                [
                    "dbus-monitor",
                    "--session",
                    "type='method_call',interface='org.freedesktop.Secret.Service',member='OpenSession'",
                ],
                stdout=monitorlog,
                stderr=subprocess.STDOUT,
                env=env,
            )
            processes.append(monitor)
            time.sleep(0.2)
            assert monitor.poll() is None

            def start_service(label):
                log = (args.output / f"gnome-{label}.log").open("w")
                files.append(log)
                process = subprocess.Popen(
                    [
                        str(args.gnome_keyring),
                        "--foreground",
                        "--components=secrets",
                        "--unlock",
                        "--control-directory",
                        str(private / "control"),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                )
                processes.append(process)
                process.stdin.write(b"synthetic-private-fixture-password\n")
                process.stdin.close()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, "private Secret Service exited"
                    response = subprocess.run(
                        [
                            "dbus-send",
                            "--session",
                            "--print-reply",
                            "--dest=org.freedesktop.DBus",
                            "/org/freedesktop/DBus",
                            "org.freedesktop.DBus.NameHasOwner",
                            "string:org.freedesktop.secrets",
                        ],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if response.returncode == 0 and "boolean true" in response.stdout:
                        return process
                    time.sleep(0.05)
                raise AssertionError("private Secret Service was not ready")

            def stage(
                label, operation, account, expected="unused", *, discover_address=False
            ):
                command = [
                    str(binaries[label]),
                    operation,
                    "hepta-private-provider-qualification",
                    account,
                    expected,
                ]
                stage_env = env.copy()
                if discover_address:
                    stage_env.pop("DBUS_SESSION_BUS_ADDRESS")
                result = subprocess.run(
                    command, env=stage_env, capture_output=True, text=True, timeout=25
                )
                receipt["steps"].append(
                    {
                        "provider": label,
                        "operation": operation,
                        "account": account,
                        "discover_address": discover_address,
                        "exit": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                (args.output / "receipt.json").write_text(
                    json.dumps(receipt, indent=2) + "\n"
                )
                assert result.returncode == 0, f"{label} {operation}: {result.stderr}"

            service = start_service("initial")
            stage("baseline", "save", "main", "old credential π")
            stage("baseline", "save", "separate", "separate account credential")
            stop(service)
            service = start_service("restarted")
            stage("candidate", "load", "main", "old credential π")
            stage(
                "candidate", "load", "main", "old credential π", discover_address=True
            )
            stage("candidate", "save", "main", "updated credential λ")
            stage("baseline", "load", "main", "updated credential λ")
            stage("candidate", "delete", "main")
            stage("baseline", "missing", "main")
            stage("candidate", "delete-missing", "main")
            stage("candidate", "load", "separate", "separate account credential")
            stage("candidate", "delete", "separate")
            stop(service)
            stop(monitor)
            monitorlog.flush()
            monitored = (args.output / "session-monitor.log").read_text()
            receipt["real_service_sessions"] = {
                "dh": monitored.count(f'string "{ALGORITHM}"'),
                "plain": monitored.count('string "plain"'),
            }
            assert receipt["real_service_sessions"]["dh"] > 0
            assert receipt["real_service_sessions"]["plain"] == 0
            rejected = args.output / "rejected-sessions.jsonl"
            rejectlog = (args.output / "reject-fixture.log").open("w")
            files.append(rejectlog)
            fixture = subprocess.Popen(
                [
                    str(args.system_python),
                    str(Path(__file__).with_name("reject_dh.py")),
                    str(rejected),
                ],
                stdout=subprocess.PIPE,
                stderr=rejectlog,
                text=True,
                env=env,
            )
            processes.append(fixture)
            assert line_with_deadline(fixture) == "READY"
            stage("candidate", "reject-dh", "rejected")
            stop(fixture)
            attempts = [json.loads(line) for line in rejected.read_text().splitlines()]
            receipt["rejected_sessions"] = attempts
            assert attempts == [{"algorithm": ALGORITHM}]
            for path, expected in inputs.items():
                assert (
                    hashlib.sha256((repo / path).read_bytes()).hexdigest() == expected
                )
            receipt["source_inputs_unchanged"] = True
            receipt["status"] = "PASS"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        for process in reversed(processes):
            stop(process)
        for handle in files:
            handle.close()
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
