#!/usr/bin/env python3
"""Qualify a derived release-only upstream lock without changing original sources.

Only the 161 local workspace crate versions may move from 0.0.0 to
0.162.1. No external dependency, checksum, source, feature or git ref may
change. The immutable upstream checkout is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

UPSTREAM_SHA = "092d3acd6bec3e3a14bdc7e7a2810ab628ab759d"
ORIGINAL_LOCK_BLOB = "1cee1174c2e937758713df47683521233a36b4f7"
RELEASE_VERSION = "0.162.1"
OLD_VERSION = "0.0.0"
EXPECTED_LOCAL_PACKAGES = 161
VERSION_LINE = re.compile(rb'(?m)^version = "0\.0\.0"$')


def qualify_release_lock(data: bytes, release: str = RELEASE_VERSION) -> tuple[bytes, list[str]]:
    if len(data) > 1024 * 1024 or not data.startswith(b"# This file is automatically"):
        raise ValueError("unexpected or oversized pinned Cargo.lock")
    original = tomllib.loads(data.decode("utf-8"))
    packages = original["package"]
    zero = [pkg for pkg in packages if pkg["version"] == OLD_VERSION]
    if len(zero) != EXPECTED_LOCAL_PACKAGES:
        raise ValueError("unexpected zero-version workspace package count")
    if len({pkg["name"] for pkg in zero}) != EXPECTED_LOCAL_PACKAGES:
        raise ValueError("duplicate local workspace package identity")
    if any("source" in pkg or "checksum" in pkg for pkg in zero):
        raise ValueError("refuse changing an external dependency version")
    if any(pkg["version"] == release for pkg in packages):
        raise ValueError("release already present in source lock")
    target = data.replace(b'version = "0.0.0"', ('version = "' + release + '"').encode())
    if len(VERSION_LINE.findall(data)) != EXPECTED_LOCAL_PACKAGES:
        raise ValueError("unexpected version-line layout")
    if target == data:
        raise ValueError("no work to qualify")
    result = tomllib.loads(target.decode("utf-8"))
    expected = {pkg["name"]: pkg for pkg in zero}
    for before, after in zip(packages, result["package"], strict=True):
        allowed = dict(before)
        if before["name"] in expected:
            allowed["version"] = release
        if after != allowed:
            raise ValueError("non-local dependency or lock field changed")
    if original["version"] != result["version"]:
        raise ValueError("lock schema changed")
    return target, sorted(expected)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, check=True, text=True, timeout=30,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--qualified-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["apply", "verify"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    source = args.upstream_root.resolve(strict=True)
    candidate = args.qualified_root.resolve(strict=True)
    if source == candidate:
        raise ValueError("qualified worktree must be physically separate")
    if git(source, "rev-parse", "HEAD") != UPSTREAM_SHA:
        raise ValueError("original upstream commit drift")
    if git(candidate, "rev-parse", "HEAD") != UPSTREAM_SHA:
        raise ValueError("qualified source commit drift")
    for root in (source, candidate):
        if git(root, "rev-parse", "HEAD:codex-rs/Cargo.lock") != ORIGINAL_LOCK_BLOB:
            raise ValueError("upstream recorded lock blob drift")
    original_path = source / "codex-rs" / "Cargo.lock"
    qualified_path = candidate / "codex-rs" / "Cargo.lock"
    if original_path.is_symlink() or qualified_path.is_symlink():
        raise ValueError("lockfile cannot be a symlink")
    original = original_path.read_bytes()
    if git(source, "hash-object", str(original_path)) != ORIGINAL_LOCK_BLOB:
        raise ValueError("original upstream lock bytes changed")
    qualified, packages = qualify_release_lock(original)
    observed = qualified_path.read_bytes()
    if args.mode == "apply":
        if observed != original:
            raise ValueError("qualified worktree did not start from exact original lock")
        qualified_path.write_bytes(qualified)
    elif observed != qualified:
        raise ValueError("qualified lock no longer matches the reviewed transformation")
    if git(candidate, "diff", "--name-only", "HEAD", "--") != "codex-rs/Cargo.lock":
        raise ValueError("tracked upstream source was modified beyond the lock")
    if git(source, "diff", "--name-only", "HEAD", "--"):
        raise ValueError("original upstream checkout has tracked modifications")
    report = {
        "schema": 1,
        "upstream_commit": UPSTREAM_SHA,
        "original_lock_git_blob": ORIGINAL_LOCK_BLOB,
        "original_lock_sha256": hashlib.sha256(original).hexdigest(),
        "qualified_lock_git_blob": git(candidate, "hash-object", str(qualified_path)),
        "qualified_lock_sha256": hashlib.sha256(qualified).hexdigest(),
        "replacement_count": len(packages),
        "replacement_from": OLD_VERSION,
        "replacement_to": RELEASE_VERSION,
        "external_package_changes": 0,
        "tracked_upstream_source_changes": ["codex-rs/Cargo.lock"],
        "original_upstream_checkout_modified": False,
        "native_tests_executed": False,
        "effect_authority": "DENY_ALL",
    }
    if args.mode == "apply":
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    else:
        if json.loads(args.report.read_text()) != report:
            raise ValueError("qualified lock report does not match reverified source")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
