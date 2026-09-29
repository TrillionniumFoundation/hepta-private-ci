#!/usr/bin/env python3
"""Reject incoherent Rama selections in platform.types qualification.

The product-facing network-proxy manifest pins the public prerelease crates it
uses directly.  The published 0.3.0-alpha.4 graph intentionally depends on the
stable 0.3.0 support crates (`rama-error`, `rama-macros`, and `rama-utils`).
Treating every `rama-*` package as if it shared one version rejects the upstream
release that Cargo actually resolves, so the lock check models the complete
published graph instead of a prefix-wide version assumption.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_VERSION = "0.3.0-alpha.4"
SUPPORT_VERSION = "0.3.0"

# Only these packages are declared by codex-network-proxy. They must remain
# exact constraints so a future Cargo resolution cannot silently move the
# product boundary to another prerelease.
DIRECT_MANIFEST_PACKAGES = (
    "rama-core",
    "rama-http",
    "rama-http-backend",
    "rama-net",
    "rama-socks5",
    "rama-tcp",
    "rama-tls-rustls",
    "rama-unix",
)

# Exact package versions selected by the published 0.3.0-alpha.4 dependency
# graph. Support crates are stable 0.3.0 releases by upstream design; accepting
# any other `rama-*` package or version is fail-closed.
LOCK_EXPECTED_VERSIONS = {
    "rama-core": EXPECTED_VERSION,
    "rama-dns": EXPECTED_VERSION,
    "rama-error": SUPPORT_VERSION,
    "rama-http": EXPECTED_VERSION,
    "rama-http-backend": EXPECTED_VERSION,
    "rama-http-core": EXPECTED_VERSION,
    "rama-http-headers": EXPECTED_VERSION,
    "rama-http-types": EXPECTED_VERSION,
    "rama-macros": SUPPORT_VERSION,
    "rama-net": EXPECTED_VERSION,
    "rama-socks5": EXPECTED_VERSION,
    "rama-tcp": EXPECTED_VERSION,
    "rama-tls-rustls": EXPECTED_VERSION,
    "rama-udp": EXPECTED_VERSION,
    "rama-unix": EXPECTED_VERSION,
    "rama-utils": SUPPORT_VERSION,
}

# Compatibility alias for scripts that historically imported this name. It now
# denotes the complete lock graph, not the set of direct manifest constraints.
REQUIRED_PACKAGES = tuple(LOCK_EXPECTED_VERSIONS)


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

    for package in DIRECT_MANIFEST_PACKAGES:
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

        for package, expected_version in LOCK_EXPECTED_VERSIONS.items():
            versions = selected.get(package, set())
            if versions != {expected_version}:
                errors.append(
                    f"lock {package} must select only {expected_version}; found {sorted(versions)}"
                )

        unexpected = sorted(
            package
            for package in selected
            if package.startswith("rama-") and package not in LOCK_EXPECTED_VERSIONS
        )
        if unexpected:
            errors.append(f"lock contains unreviewed Rama packages: {unexpected}")

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
        f"({len(DIRECT_MANIFEST_PACKAGES)} exact direct pins; "
        f"{len(LOCK_EXPECTED_VERSIONS)} reviewed lock packages)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
