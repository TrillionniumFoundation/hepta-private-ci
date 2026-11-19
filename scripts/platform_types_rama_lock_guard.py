#!/usr/bin/env python3
"""Reject incoherent Rama selections in platform.types qualification.

Cargo's ordinary prerelease requirement semantics permit upgrading
`0.3.0-alpha.4` requirements to the stable `0.3.0` release. That resolution is
not source-compatible for this graph: `rama-core 0.3.0-alpha.4` imports APIs
that are absent from `rama-error 0.3.0`. The product manifest therefore pins
all directly relevant product and support crates exactly, and this guard checks
the complete reviewed alpha.4 graph rather than accepting a mixed release.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_VERSION = "0.3.0-alpha.4"

# These packages are declared directly by codex-network-proxy. The three
# support crates are intentionally present even though most symbols are reached
# transitively: their exact constraints prevent Cargo from replacing the
# prerelease APIs with the incompatible stable 0.3.0 releases.
DIRECT_MANIFEST_PACKAGES = (
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

LOCK_PACKAGES = (
    "rama-core",
    "rama-dns",
    "rama-error",
    "rama-http",
    "rama-http-backend",
    "rama-http-core",
    "rama-http-headers",
    "rama-http-types",
    "rama-macros",
    "rama-net",
    "rama-socks5",
    "rama-tcp",
    "rama-tls-rustls",
    "rama-udp",
    "rama-unix",
    "rama-utils",
)
LOCK_EXPECTED_VERSIONS = {package: EXPECTED_VERSION for package in LOCK_PACKAGES}

# Compatibility alias for scripts that historically imported this name.
REQUIRED_PACKAGES = LOCK_PACKAGES


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
        f"{len(LOCK_EXPECTED_VERSIONS)} exact lock packages at {EXPECTED_VERSION})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
