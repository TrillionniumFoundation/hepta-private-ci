#!/usr/bin/env python3
"""Install and bind CI Cargo commands to the exact workspace Rust toolchain."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib


def install(root, github_env, extra_components):
    source = root / "codex-rs/rust-toolchain.toml"
    contents = source.read_bytes()
    toolchain = tomllib.loads(contents.decode("utf-8"))["toolchain"]
    channel = toolchain["channel"]
    if not isinstance(channel, str) or not re.fullmatch(r"1\.\d+\.\d+", channel):
        raise ValueError("CI requires an exact workspace Rust release")
    components = sorted(set(toolchain.get("components", []) + extra_components))
    if any(not re.fullmatch(r"[a-z][a-z0-9-]*", item) for item in components):
        raise ValueError("invalid Rust component")
    command = [
        "rustup",
        "toolchain",
        "install",
        channel,
        "--profile",
        "minimal",
        "--no-self-update",
    ]
    for component in components:
        command.extend(["--component", component])
    subprocess.run(command, cwd=root, check=True)
    environment = dict(os.environ, RUSTUP_TOOLCHAIN=channel)
    version = subprocess.check_output(
        ["rustc", "--version", "--verbose"], cwd=root, env=environment, text=True
    )
    release = re.findall(r"^release: (\S+)$", version, re.MULTILINE)
    if release != [channel]:
        raise ValueError(f"installed rustc release differs from {channel}: {release}")
    with github_env.open("a", encoding="utf-8") as stream:
        stream.write(f"RUSTUP_TOOLCHAIN={channel}\n")
    return {
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(contents).hexdigest(),
        "channel": channel,
        "components": components,
        "rustc_version": version,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--component", action="append", default=[])
    args = parser.parse_args()
    receipt = install(
        Path(__file__).resolve().parents[1], args.github_env, args.component
    )
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
