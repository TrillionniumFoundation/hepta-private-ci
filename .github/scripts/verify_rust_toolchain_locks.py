#!/usr/bin/env python3
"""Verify generated locks against the official distribution and exact input tree."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from urllib.parse import urlparse


def verify(root: Path, output: Path) -> dict:
    manifest = tomllib.loads((output / "channel-rust-1.99.0.toml").read_text())
    if manifest["pkg"]["rust"]["version"].split()[0] != "1.99.0":
        raise ValueError("the official manifest does not identify Rust 1.99.0")
    official = {}

    def register(url: str, digest: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "static.rust-lang.org":
            raise ValueError("unexpected Rust distribution origin")
        official[Path(parsed.path).name] = digest

    for package in manifest["pkg"].values():
        for target in package.get("target", {}).values():
            url = target.get("xz_url")
            if url and target.get("available"):
                register(url, target["xz_hash"])
    # The compiler source archive is an artifact, not a rustup package. Bazel
    # binds it alongside rustc/rust-std, so the package table alone is incomplete.
    for artifacts in (
        manifest.get("artifacts", {}).get("source-code", {}).get("target", {}).values()
    ):
        for artifact in artifacts:
            register(artifact["url"], artifact["hash-sha256"])

    extension = "@@rules_rs+//rs/toolchains:module_extension.bzl%toolchains"
    before = json.loads((output / "MODULE.bazel.lock.before").read_text())
    after = json.loads((root / "MODULE.bazel.lock").read_text())
    old_facts = before["facts"][extension]
    facts = after["facts"][extension]
    required = {
        re.sub(r"-1\.96\.0(?=-|\.tar\.xz$)", "-1.99.0", name) for name in old_facts
    }
    if set(facts) != required:
        raise ValueError("Bazel Rust archive coverage changed or stale facts remain")
    for name, digest in facts.items():
        if official.get(name) != digest:
            raise ValueError(
                f"Bazel archive differs from official Rust manifest: {name}"
            )

    old_nix = json.loads((output / "flake.lock.before").read_text())
    new_nix = json.loads((root / "flake.lock").read_text())
    old_overlay = old_nix["nodes"].pop("rust-overlay")
    new_overlay = new_nix["nodes"].pop("rust-overlay")
    if old_nix != new_nix:
        raise ValueError("Nix refresh changed inputs beyond rust-overlay")
    if {k: v for k, v in old_overlay.items() if k != "locked"} != {
        k: v for k, v in new_overlay.items() if k != "locked"
    }:
        raise ValueError("Nix overlay source or dependency wiring changed")
    if old_overlay["locked"] == new_overlay["locked"]:
        raise ValueError("Nix overlay was not refreshed")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=root, text=True
    ).splitlines()
    if set(changed) != {"MODULE.bazel.lock", "flake.lock"}:
        raise ValueError(f"unexpected source mutations: {changed}")
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=root, text=True
    )
    if source != (output / "source.txt").read_text():
        raise ValueError("source identity changed during lock generation")
    return {
        "sourceCommit": source.splitlines()[0],
        "sourceTree": source.splitlines()[1],
        "rustVersion": "1.99.0",
        "verifiedArchives": len(facts),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "lockSha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("MODULE.bazel.lock", "flake.lock")
        },
        "compiledOrTested": False,
    }


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    receipt = verify(Path.cwd(), destination)
    (destination / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
