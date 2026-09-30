#!/usr/bin/env python3
"""Compile the platform.wire production-only public surface.

The positive fixture must compile with only the `production` feature. Every
negative fixture must fail to type-check, proving that raw authenticated owners,
full-session escape, raw-envelope sealing, unbound codecs and secret cloning are
not available from that feature surface.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
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


def manifest() -> str:
    return f'''[package]
name = "platform-wire-production-surface"
version = "0.0.0"
edition = "2024"
publish = false

[workspace]

[dependencies]
codex-hepta-wire = {{ path = {str(WIRE)!r}, default-features = false, features = ["production"] }}
codex-hepta-types = {{ path = {str(TYPES)!r} }}
'''


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
            raise SystemExit(f"negative production fixture unexpectedly compiled: {source.name}")
        if result.returncode != 0 and expect_success:
            raise SystemExit(
                f"production surface fixture failed: {source.name}\n{result.stderr}"
            )


def verify() -> None:
    missing = [
        name
        for name in ("pass.rs", *NEGATIVE)
        if not (FIXTURES / name).is_file()
    ]
    if missing:
        raise SystemExit("missing production surface fixtures: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="platform-wire-surface-target-") as directory:
        target = Path(directory)
        check(FIXTURES / "pass.rs", expect_success=True, target=target)
        for name in NEGATIVE:
            check(FIXTURES / name, expect_success=False, target=target)


def self_test() -> None:
    assert "raw_owners.rs" in NEGATIVE
    text = manifest()
    assert 'default-features = false' in text
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
