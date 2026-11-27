#!/usr/bin/python3
"""Build both transports and verify synthetic credentials on a private D-Bus."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
import tomllib
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(backend, output, environment):
    command = [
        "cargo",
        "build",
        "--locked",
        "--manifest-path",
        str(HERE / "Cargo.toml"),
        "--no-default-features",
        "--features",
        backend,
    ]
    with (output / f"build-{backend}.log").open("w") as log:
        subprocess.run(
            command,
            cwd=REPO,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=900,
        )
    source = (
        Path(environment["CARGO_TARGET_DIR"]) / "debug/keyring-transport-interop-probe"
    )
    binary = output / f"{backend}-probe"
    shutil.copy2(source, binary)
    return {"command": command, "sha256": sha256(binary)}


def session(output):
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS"), (
        "private session address is required"
    )
    fixture_log = (output / "fixture-stderr.log").open("w")
    server = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "secret_service_fixture.py"),
            str(output / "server-receipt.json"),
        ],
        stdout=subprocess.PIPE,
        stderr=fixture_log,
        text=True,
    )
    receipts = []
    try:
        if (
            not select.select([server.stdout], [], [], 10)[0]
            or server.stdout.readline().strip() != "READY"
        ):
            raise RuntimeError("synthetic Secret Service failed to start")
        # Both directions bind persistence to the same service/account attributes.
        sequence = [
            ("baseline", "seed"),
            ("candidate", "update"),
            ("baseline", "read_updated"),
            ("candidate", "delete"),
            ("baseline", "missing"),
            ("candidate", "seed"),
            ("baseline", "update"),
            ("candidate", "read_updated"),
            ("baseline", "delete"),
            ("candidate", "missing"),
            ("candidate", "keyutils_cycle"),
        ]
        for backend, mode in sequence:
            command = [str(output / f"{backend}-probe"), mode]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            row = {
                "backend": backend,
                "mode": mode,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            receipts.append(row)
            (output / "client-receipt.json").write_text(
                json.dumps(receipts, indent=2) + "\n"
            )
            if result.returncode:
                raise RuntimeError(f"{backend} {mode} failed: {result.stderr}")
            assert json.loads(result.stdout) == {
                "backend": backend,
                "mode": mode,
                "passed": True,
            }
        receipt = json.loads((output / "server-receipt.json").read_text())
        events = receipt["events"]
        assert not [row for row in events if row["operation"] == "fixture_error"]
        sessions = [row for row in events if row["operation"] == "open_session"]
        assert sessions and all(
            row["algorithm"] == "dh-ietf1024-sha256-aes128-cbc-pkcs7"
            for row in sessions
        )
        assert len([row for row in events if row["operation"] == "create"]) == 3
        assert (
            len([row for row in events if row["operation"] == "injected_failure"]) == 7
        )
        assert len([row for row in events if row["operation"] == "unlock"]) == 1
        assert len([row for row in events if row["operation"] == "decrypt"]) == 5
        assert receipt["remaining_items"] == 6
        assert receipt["synthetic_only"]
    finally:
        # Only this fixture process is terminated; dbus-run-session owns its bus.
        server.terminate()
        server.wait(timeout=5)
        fixture_log.close()
    print(
        json.dumps(
            {
                "passed": True,
                "client_steps": len(receipts),
                "encrypted_sessions": len(sessions),
            }
        )
    )


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    # The probe deliberately retains the old transport solely as a migration
    # reader/writer. Require each shared package to match the production lock.
    production = tomllib.loads((REPO / "codex-rs/Cargo.lock").read_text())["package"]
    probe = tomllib.loads((HERE / "Cargo.lock").read_text())["package"]
    pin_names = {"keyring", "secret-service", "zbus", "tracing"}
    expected = [
        {
            "name": row["name"],
            "version": row["version"],
            "checksum": row.get("checksum"),
        }
        for row in production
        if row["name"] in pin_names
    ]
    observed = [
        {
            "name": row["name"],
            "version": row["version"],
            "checksum": row.get("checksum"),
        }
        for row in probe
        if row["name"] in pin_names
    ]
    assert expected and all(row in observed for row in expected), (expected, observed)
    assert {row["name"] for row in expected} == pin_names
    assert {row["version"] for row in expected if row["name"] == "secret-service"} == {
        "6.0.0"
    }
    assert {row["checksum"] for row in expected if row["name"] == "keyring"} == {None}
    assert {
        "name": "keyring",
        "version": "3.6.3",
        "checksum": "eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c",
    } in observed
    environment = os.environ.copy()
    environment.update(
        {
            "CARGO_INCREMENTAL": "0",
            "CARGO_BUILD_JOBS": "2",
            "CARGO_PROFILE_DEV_DEBUG": "0",
            "HEPTA_KEYRING_TEST_ACCOUNT": "hepta-ci-" + uuid.uuid4().hex,
        }
    )
    environment.setdefault("CARGO_TARGET_DIR", str(output / "target"))
    identity = {
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "production_lock_sha256": sha256(REPO / "codex-rs/Cargo.lock"),
        "probe_lock_sha256": sha256(HERE / "Cargo.lock"),
        "shared_package_pins": expected,
        "source_hashes": {
            str(p.relative_to(REPO)): sha256(p)
            for p in sorted(HERE.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.name != "Cargo.lock"
        },
    }
    (output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    started = time.monotonic()
    builds = {
        backend: build(backend, output, environment)
        for backend in ["baseline", "candidate"]
    }
    linked = subprocess.check_output(
        ["ldd", str(output / "candidate-probe")], text=True
    )
    (output / "candidate-ldd.txt").write_text(linked)
    assert "libdbus-1.so" not in linked, (
        "pure Rust transport must not require a system libdbus"
    )
    command = [
        "dbus-run-session",
        "--",
        sys.executable,
        str(Path(__file__).resolve()),
        "--session",
        "--output",
        str(output),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, env=environment, timeout=120
    )
    receipt = {
        "source_sha": identity["source_sha"],
        "builds": builds,
        "session_command": command,
        "session_exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "wall_seconds": time.monotonic() - started,
        "passed": result.returncode == 0,
    }
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session", action="store_true")
    args = parser.parse_args()
    if args.session:
        session(args.output.resolve())
    else:
        run(args.output.resolve())
