#!/usr/bin/env python3
"""Reject incoherent Rama prerelease selections in platform.types qualification."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_VERSION = "0.3.0-alpha.4"
REQUIRED_PACKAGES = (
    "rama-core",
    "rama-error",
    "rama-http",
    "rama-http-backend",
    "rama-macros",
    "rama-net",
    "rama-socks5",
    "rama-tcp",
    "rama-tls-rustls",
    "rama-unix",
    "rama-utils",
)


class RamaLockError(RuntimeError):
    """The manifest or selected Cargo graph mixes Rama generations."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RamaLockError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RamaLockError(f"TOML object required: {path}")
    return value


def _dependency_versions(value: Any) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        dependencies = node.get("dependencies")
        if isinstance(dependencies, dict):
            for name, declaration in dependencies.items():
                version: str | None = None
                if isinstance(declaration, str):
                    version = declaration
                elif isinstance(declaration, dict) and isinstance(
                    declaration.get("version"), str
                ):
                    version = declaration["version"]
                if version is not None:
                    found.setdefault(str(name), set()).add(version)
        for child in node.values():
            visit(child)

    visit(value)
    return found


def validate(manifest_path: Path, lock_path: Path) -> None:
    manifest = _read_toml(manifest_path)
    lock = _read_toml(lock_path)
    declared = _dependency_versions(manifest)
    errors: list[str] = []
    exact = f"={EXPECTED_VERSION}"
    for package in REQUIRED_PACKAGES:
        versions = declared.get(package, set())
        if versions != {exact}:
            errors.append(
                f"manifest {package} must be pinned exactly to {exact}; found {sorted(versions)}"
            )

    selected: dict[str, set[str]] = {}
    packages = lock.get("package")
    if not isinstance(packages, list):
        errors.append("Cargo.lock package array is missing")
    else:
        for row in packages:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            version = row.get("version")
            if isinstance(name, str) and isinstance(version, str):
                selected.setdefault(name, set()).add(version)
        for package in REQUIRED_PACKAGES:
            versions = selected.get(package, set())
            if versions != {EXPECTED_VERSION}:
                errors.append(
                    f"lock {package} must select only {EXPECTED_VERSION}; found {sorted(versions)}"
                )

    if errors:
        raise RamaLockError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("codex-rs/network-proxy/Cargo.toml"),
    )
    parser.add_argument("--lock", type=Path, default=Path("codex-rs/Cargo.lock"))
    args = parser.parse_args()
    try:
        validate(args.manifest, args.lock)
    except RamaLockError as error:
        print(f"platform.types Rama lock guard failed: {error}", file=sys.stderr)
        return 1
    print(
        "platform.types Rama lock guard: coherent "
        f"({len(REQUIRED_PACKAGES)} packages at {EXPECTED_VERSION})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
