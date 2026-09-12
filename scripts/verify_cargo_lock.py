#!/usr/bin/env python3
"""Verify the repository Cargo lockfile is complete and parseable.

This check is intentionally independent of Cargo.  A truncated or otherwise
non-TOML lockfile can make every ``cargo --locked`` job fail before it reaches
the package under test, so CI checks the lockfile before invoking Cargo.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCKFILE = ROOT / "codex-rs" / "Cargo.lock"
EXPECTED_PACKAGE_COUNT = 1517
REQUIRED_PACKAGES = frozenset(
    {
        "codex-hepta-agentd",
        "codex-hepta-control-plane",
        "codex-hepta-intelligence-eval",
        "codex-hepta-learning-artifacts",
        "codex-hepta-learning-ledger",
        "codex-hepta-neuron",
        "codex-hepta-ndu",
        "codex-hepta-objective",
        "codex-hepta-runtime",
        "codex-hepta-shadow-qualification",
        "codex-hepta-types",
    }
)


class VerificationFailure(RuntimeError):
    """The lockfile violates a repository integrity invariant."""


def validate_lock_document(document: str, *, source: str = "Cargo.lock") -> int:
    """Parse and validate one lockfile document, returning its package count."""

    try:
        data: dict[str, Any] = tomllib.loads(document)
    except tomllib.TOMLDecodeError as error:
        raise VerificationFailure(f"{source} is not valid TOML: {error}") from error

    packages = data.get("package")
    if not isinstance(packages, list):
        raise VerificationFailure(f"{source} must contain a package array")
    package_names: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise VerificationFailure(f"package[{index}] must be a TOML table")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not name:
            raise VerificationFailure(f"package[{index}] has no non-empty name")
        if not isinstance(version, str) or not version:
            raise VerificationFailure(f"package[{index}] {name!r} has no version")
        package_names.add(name)

    package_count = len(packages)
    if package_count != EXPECTED_PACKAGE_COUNT:
        raise VerificationFailure(
            f"{source} package count changed: expected "
            f"{EXPECTED_PACKAGE_COUNT}, got {package_count}"
        )
    missing = sorted(REQUIRED_PACKAGES - package_names)
    if missing:
        raise VerificationFailure(
            f"{source} is missing required packages: {', '.join(missing)}"
        )
    return package_count


def verify_lockfile(path: Path = DEFAULT_LOCKFILE) -> int:
    """Read and validate *path*, preserving useful OS errors for CI output."""

    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise VerificationFailure(f"cannot read {path}: {error}") from error
    return validate_lock_document(document, source=str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "lockfile",
        nargs="?",
        type=Path,
        default=DEFAULT_LOCKFILE,
        help="lockfile to validate (default: codex-rs/Cargo.lock)",
    )
    args = parser.parse_args(argv)
    try:
        count = verify_lockfile(args.lockfile)
    except VerificationFailure as error:
        print(f"cargo-lock verification failed: {error}", file=sys.stderr)
        return 1
    print(f"cargo-lock verification passed: {args.lockfile} ({count} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
