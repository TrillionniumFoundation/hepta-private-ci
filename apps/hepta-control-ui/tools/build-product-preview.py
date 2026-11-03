"""Build the real gateway example and record its frozen source and binary bytes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[3]


def backend_toolchain():
    manifest = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())
    channel = manifest.get("toolchain", {}).get("channel")
    if not isinstance(channel, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", channel):
        raise ValueError("Gateway preview requires an exact backend Rust release pin")
    return channel


def git(*args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=ROOT, text=True
    ).strip()


def identity():
    status = git("status", "--porcelain", "--untracked-files=normal")
    if status:
        raise ValueError(
            "Gateway preview evidence requires a committed clean source; dirty paths:\n"
            + status[:4096]
        )
    paths = git(
        "ls-files",
        "--",
        "codex-rs/hepta-native-gateway",
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml",
    ).splitlines()
    return {
        "sourceCommit": git("rev-parse", "HEAD"),
        "sourceTree": git("rev-parse", "HEAD^{tree}"),
        "sourceHashes": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in paths
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--print-toolchain", action="store_true")
    args = parser.parse_args()
    if args.print_toolchain:
        print(backend_toolchain())
        return
    if args.target_dir is None:
        parser.error("--target-dir is required for a build")
    before = identity()
    channel = backend_toolchain()
    target = args.target_dir.resolve()
    env = dict(
        os.environ,
        RUSTUP_TOOLCHAIN=channel,
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_JOBS="1",
        CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0",
    )
    version = subprocess.check_output(
        ["rustc", "--version"], env=env, text=True
    ).strip()
    if not version.startswith(f"rustc {channel} "):
        raise ValueError(f"Gateway example requires the backend Rust{channel} pin")
    subprocess.run(
        [
            "cargo",
            "build",
            "--manifest-path",
            str(ROOT / "codex-rs/Cargo.toml"),
            "-p",
            "codex-hepta-native-gateway",
            "--example",
            "ui_product_preview",
            "--locked",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    if identity() != before:
        raise ValueError("Gateway source changed while building")
    binary = target / "debug/examples/ui_product_preview"
    before.update(
        compiler=version,
        binarySha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        binaryBytes=binary.stat().st_size,
    )
    binary.with_name(binary.name + ".hepta-build.json").write_text(
        json.dumps(before, indent=2) + "\n"
    )
    print(binary)


if __name__ == "__main__":
    main()
