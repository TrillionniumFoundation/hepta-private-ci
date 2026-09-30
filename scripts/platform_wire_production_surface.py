#!/usr/bin/env python3
"""Compile the platform.wire production-only public surface.

The positive fixture must compile with only the `production` feature. Every
negative fixture must fail to type-check, proving that raw authenticated owners,
full-session escape, raw-envelope sealing, unbound codecs and secret cloning are
not available from that feature surface.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WIRE = ROOT / "codex-rs/hepta-wire"
TYPES = ROOT / "codex-rs/hepta-types"
FIXTURES = WIRE / "tests/production_surface"
NEGATIVE = (
    "raw_owners.rs",
    "session_escape.rs",
    "raw_envelope.rs",
    "unbound_codec.rs",
    "clone_key.rs",
)

# A build or dependency failure is not proof that a forbidden API is absent.
# Require diagnostics from the consumer itself for each intended restriction.
DIAGNOSTICS = {
    "raw_owners.rs": (
        ("E0432", "E0603"),
        (
            "AuthenticatedWireSession",
            "ManagedAuthenticatedWireSession",
            "ManagedRecordStream",
            "WireSession",
        ),
    ),
    "session_escape.rs": (("E0599",), ("session",)),
    "raw_envelope.rs": (("E0599",), ("seal_envelope",)),
    "unbound_codec.rs": (("E0277",), ("BoundPayloadCodec",)),
    "clone_key.rs": (("E0308",), ("mismatched types",)),
}


def expected_rejection(source: Path, output: str) -> bool:
    codes, fragments = DIAGNOSTICS[source.name]
    messages = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("reason") != "compiler-message":
            continue
        if item.get("target", {}).get("name") != "platform-wire-production-surface":
            continue
        message = item.get("message", {})
        if (
            message.get("level") == "error"
            and isinstance(message.get("code"), dict)
            and message["code"].get("code") in codes
        ):
            messages.append(message.get("message", ""))
    return all(
        any(
            re.search(r"\b" + re.escape(fragment) + r"\b", message)
            for message in messages
        )
        for fragment in fragments
    )


def manifest() -> str:
    return f"""[package]
name = "platform-wire-production-surface"
version = "0.0.0"
edition = "2024"
publish = false

[workspace]

[dependencies]
codex-hepta-wire = {{ path = {str(WIRE)!r}, default-features = false, features = ["production"] }}
codex-hepta-types = {{ path = {str(TYPES)!r} }}
"""


def check(source: Path, *, expect_success: bool, target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="platform-wire-surface-") as directory:
        root = Path(directory)
        (root / "Cargo.toml").write_text(manifest(), encoding="utf-8")
        src = root / "src"
        src.mkdir()
        shutil.copyfile(source, src / "main.rs")
        environment = dict(os.environ)
        environment["CARGO_TARGET_DIR"] = str(target)
        result = subprocess.run(
            [
                "cargo",
                "check",
                "--quiet",
                "--message-format=json",
                "--manifest-path",
                str(root / "Cargo.toml"),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0 and not expect_success:
            raise SystemExit(
                f"negative production fixture unexpectedly compiled: {source.name}"
            )
        if result.returncode != 0 and expect_success:
            raise SystemExit(
                f"production surface fixture failed: {source.name}\n{result.stderr}"
            )
        if (
            result.returncode != 0
            and not expect_success
            and not expected_rejection(source, result.stdout)
        ):
            raise SystemExit(
                f"negative production fixture did not prove its API restriction: {source.name}\n"
                f"{result.stdout}\n{result.stderr}"
            )


def verify() -> None:
    missing = [
        name for name in ("pass.rs", *NEGATIVE) if not (FIXTURES / name).is_file()
    ]
    if missing:
        raise SystemExit("missing production surface fixtures: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(
        prefix="platform-wire-surface-target-"
    ) as directory:
        target = Path(directory)
        check(FIXTURES / "pass.rs", expect_success=True, target=target)
        for name in NEGATIVE:
            check(FIXTURES / name, expect_success=False, target=target)


def self_test() -> None:
    assert "raw_owners.rs" in NEGATIVE
    text = manifest()
    assert "default-features = false" in text
    assert 'features = ["production"]' in text
    print("platform.wire production surface self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"))
    args = parser.parse_args()
    if args.command == "verify":
        verify()
        print("platform.wire production surface verified")
    else:
        self_test()


if __name__ == "__main__":
    main()
