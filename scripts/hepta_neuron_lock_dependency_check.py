#!/usr/bin/env python3
"""Early, offline direct-path Cargo.lock dependency check for the Neuron Worker.

This catches a narrow manifest/lock drift before expensive multi-crate jobs.
It does NOT replace Cargo --locked, resolver checks, or dependency security scans.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib


class LockMismatch(ValueError):
    """Source manifest path dependency is not represented in the frozen lock."""


def read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise LockMismatch(
            f"cannot parse source manifest or lock at {path}: {exc}"
        ) from exc


def path_dependencies(manifest: dict) -> set[str]:
    result: set[str] = set()
    groups = [
        manifest.get("dependencies", {}),
        manifest.get("build-dependencies", {}),
        manifest.get("dev-dependencies", {}),
    ]
    for target in manifest.get("target", {}).values():
        if not isinstance(target, dict):
            raise LockMismatch("unexpected target section")
        groups.extend(
            target.get(n, {})
            for n in ("dependencies", "build-dependencies", "dev-dependencies")
        )
    for group in groups:
        if not isinstance(group, dict):
            raise LockMismatch("invalid dependency table")
        for declared_name, config in group.items():
            if isinstance(config, dict) and "path" in config:
                result.add(config.get("package", declared_name))
    return result


def verify(manifest_path: Path, lock_path: Path) -> dict:
    manifest = read_toml(manifest_path)
    lock = read_toml(lock_path)
    name = manifest.get("package", {}).get("name")
    if not isinstance(name, str) or not name:
        raise LockMismatch("missing manifest package name")
    if not isinstance(lock.get("package"), list):
        raise LockMismatch("missing Cargo.lock package records")
    packages = [p for p in lock["package"] if p.get("name") == name]
    if len(packages) != 1:
        raise LockMismatch(
            f"expected exactly one Cargo.lock entry for {name}; found {len(packages)}"
        )
    locked = packages[0].get("dependencies", [])
    if not isinstance(locked, list) or any(not isinstance(d, str) for d in locked):
        raise LockMismatch("invalid locked dependency list")
    locked_names = {dep.split(" ", 1)[0] for dep in locked}
    required = path_dependencies(manifest)
    missing = sorted(required - locked_names)
    if missing:
        raise LockMismatch(
            f"Cargo.lock missing direct path dependencies for {name}: {', '.join(missing)}"
        )
    return {
        "package": name,
        "checked_direct_path_dependencies": sorted(required),
        "status": "direct_path_dependencies_present_not_full_cargo_resolution",
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "codex-rs/hepta-infer-worker-host/Cargo.toml",
    )
    parser.add_argument("--lock", type=Path, default=root / "codex-rs/Cargo.lock")
    args = parser.parse_args(argv)
    try:
        report = verify(args.manifest, args.lock)
    except LockMismatch as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"PASS {report['package']}: {len(report['checked_direct_path_dependencies'])} direct path dependencies in Cargo.lock; run cargo --locked for full resolution"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
