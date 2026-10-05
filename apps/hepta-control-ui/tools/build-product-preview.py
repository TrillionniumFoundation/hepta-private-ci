"""Build the real gateway example and record its frozen source and binary bytes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


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
    parser.add_argument("--target-dir", type=Path, required=True)
    args = parser.parse_args()
    before = identity()
    target = args.target_dir.resolve()
    env = dict(
        os.environ,
        RUSTUP_TOOLCHAIN="1.96.0",
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_JOBS="1",
        CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0",
    )
    version = subprocess.check_output(
        ["rustc", "--version"], env=env, text=True
    ).strip()
    if not version.startswith("rustc 1.96.0 "):
        raise ValueError("Gateway example requires the backend Rust1.96.0 pin")
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
