#!/usr/bin/env python3
"""Verify the repository Cargo lockfile is complete and parseable.

Python 3.11+ uses tomllib. Ubuntu 22.04 qualification runners use Python 3.10,
so this module also carries a strict parser for Cargo.lock's generated TOML
subset instead of silently skipping lockfile validation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 qualification hosts.
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCKFILE = ROOT / "codex-rs" / "Cargo.lock"
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


_ASSIGNMENT = re.compile(r"([A-Za-z0-9_-]+)\s*=\s*(.*)")
_ARRAY_TABLE = re.compile(r"\[\[([A-Za-z0-9_.-]+)\]\]")
_STANDARD_TABLE = re.compile(r"\[([A-Za-z0-9_.-]+)\]")
_INTEGER = re.compile(r"[+-]?[0-9][0-9_]*")


def _strip_comment(line: str) -> str:
    quoted = False
    escaped = False
    output: list[str] = []
    for character in line:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\" and quoted:
            output.append(character)
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            output.append(character)
            continue
        if character == "#" and not quoted:
            break
        output.append(character)
    if quoted:
        raise VerificationFailure("Cargo.lock contains an unterminated string")
    return "".join(output).strip()


def _array_delta(value: str) -> int:
    quoted = False
    escaped = False
    delta = 0
    for character in value:
        if escaped:
            escaped = False
            continue
        if character == "\\" and quoted:
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character == "[":
            delta += 1
        elif character == "]":
            delta -= 1
    if quoted:
        raise VerificationFailure("Cargo.lock contains an unterminated string")
    return delta


def _basic_value(value: str, *, source: str, line_number: int) -> Any:
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise VerificationFailure(
                f"{source}:{line_number} has an invalid TOML basic string: {error}"
            ) from error
        if not isinstance(parsed, str):
            raise VerificationFailure(f"{source}:{line_number} expected a string")
        return parsed
    if _INTEGER.fullmatch(value):
        return int(value.replace("_", ""))
    if value in {"true", "false"}:
        return value == "true"
    raise VerificationFailure(
        f"{source}:{line_number} uses unsupported or malformed generated TOML value"
    )


def parse_cargo_lock_subset(document: str, *, source: str) -> dict[str, Any]:
    """Parse the strict generated Cargo.lock subset used by Cargo format v4."""

    root: dict[str, Any] = {}
    packages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = root
    current_table = "<root>"
    pending_key: str | None = None
    pending_value: list[str] = []
    pending_balance = 0
    pending_target: dict[str, Any] | None = None
    pending_line = 0

    for line_number, raw_line in enumerate(document.splitlines(), 1):
        line = _strip_comment(raw_line)
        if not line:
            continue

        if pending_key is not None:
            pending_value.append(line)
            pending_balance += _array_delta(line)
            if pending_balance < 0:
                raise VerificationFailure(
                    f"{source}:{line_number} has an invalid multiline array"
                )
            if pending_balance == 0:
                assert pending_target is not None
                if pending_key in pending_target:
                    raise VerificationFailure(
                        f"{source}:{pending_line} duplicates key {pending_key!r}"
                    )
                pending_target[pending_key] = ("array", "\n".join(pending_value))
                pending_key = None
                pending_value = []
                pending_target = None
            continue

        array_table = _ARRAY_TABLE.fullmatch(line)
        if array_table:
            current_table = array_table.group(1)
            if current_table == "package":
                current = {}
                packages.append(current)
            else:
                current = {}
            continue

        standard_table = _STANDARD_TABLE.fullmatch(line)
        if standard_table:
            current_table = standard_table.group(1)
            current = {}
            continue

        assignment = _ASSIGNMENT.fullmatch(line)
        if assignment is None or current is None:
            raise VerificationFailure(
                f"{source}:{line_number} is not generated Cargo.lock TOML"
            )
        key, value = assignment.groups()
        if not value:
            raise VerificationFailure(f"{source}:{line_number} has an empty value")
        if value.startswith("["):
            balance = _array_delta(value)
            if balance < 0:
                raise VerificationFailure(
                    f"{source}:{line_number} has an invalid array value"
                )
            if balance == 0:
                if key in current:
                    raise VerificationFailure(
                        f"{source}:{line_number} duplicates key {key!r}"
                    )
                current[key] = ("array", value)
            else:
                pending_key = key
                pending_value = [value]
                pending_balance = balance
                pending_target = current
                pending_line = line_number
            continue

        parsed = _basic_value(value, source=source, line_number=line_number)
        if key in current:
            raise VerificationFailure(
                f"{source}:{line_number} duplicates key {key!r} in {current_table}"
            )
        current[key] = parsed

    if pending_key is not None:
        raise VerificationFailure(
            f"{source}:{pending_line} contains a truncated multiline array"
        )
    if not isinstance(root.get("version"), int):
        raise VerificationFailure(f"{source} has no integer lockfile version")
    return {"version": root["version"], "package": packages}


def _parse_document(document: str, *, source: str) -> dict[str, Any]:
    if tomllib is not None:
        try:
            return tomllib.loads(document)
        except tomllib.TOMLDecodeError as error:
            raise VerificationFailure(f"{source} is not valid TOML: {error}") from error
    return parse_cargo_lock_subset(document, source=source)


def validate_lock_document(document: str, *, source: str = "Cargo.lock") -> int:
    """Parse and validate one lockfile document, returning its package count."""

    data = _parse_document(document, source=source)
    packages = data.get("package")
    if not isinstance(packages, list):
        raise VerificationFailure(f"{source} must contain a package array")
    package_names: set[str] = set()
    package_identities: set[tuple[str, str, str | None]] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise VerificationFailure(f"package[{index}] must be a TOML table")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not name:
            raise VerificationFailure(f"package[{index}] has no non-empty name")
        if not isinstance(version, str) or not version:
            raise VerificationFailure(f"package[{index}] {name!r} has no version")
        source_id = package.get("source")
        if source_id is not None and not isinstance(source_id, str):
            raise VerificationFailure(f"package[{index}] {name!r} has invalid source")
        identity = (name, version, source_id)
        if identity in package_identities:
            raise VerificationFailure(
                f"{source} contains duplicate package identity: "
                f"{name} {version} {source_id or 'workspace'}"
            )
        package_identities.add(identity)
        package_names.add(name)

    package_count = len(packages)
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
