#!/usr/bin/env python3
"""Fail closed if the 15 tracked RustSec advisories are ignored by policy."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

TRACKED_RUSTSEC = frozenset(
    ["RUSTSEC-2024-0449", "RUSTSEC-2026-0318", "RUSTSEC-2026-0319"]
    + [f"RUSTSEC-2026-{number:04d}" for number in range(346, 350)]
    + [f"RUSTSEC-2026-{number:04d}" for number in range(367, 373)]
    + ["RUSTSEC-2026-0385", "RUSTSEC-2026-0387"]
)

POLICIES = (Path("codex-rs/deny.toml"), Path("codex-rs/.cargo/audit.toml"))


def ignored_tracked_advisories(text: str) -> list[str]:
    """Return only the tracked advisory IDs hidden by one valid TOML policy."""
    entries = tomllib.loads(text).get("advisories", {}).get("ignore", [])
    if not isinstance(entries, list):
        raise ValueError("[advisories].ignore must be a list")
    ignored = []
    for entry in entries:
        if isinstance(entry, str):
            advisory_id = entry
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            advisory_id = entry["id"]
        else:
            raise ValueError("[advisories].ignore contains a malformed entry")
        if advisory_id in TRACKED_RUSTSEC:
            ignored.append(advisory_id)
    return sorted(set(ignored))


def violations(root: Path) -> dict[str, list[str]]:
    bad: dict[str, list[str]] = {}
    for relative in POLICIES:
        matches = ignored_tracked_advisories(
            (root / relative).read_text(encoding="utf-8")
        )
        if matches:
            bad[str(relative)] = matches
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    try:
        found = violations(args.repo_root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(
            f"RustSec policy guard could not read or parse its inputs: {error}",
            file=sys.stderr,
        )
        return 1
    if found:
        for path, ids in found.items():
            print(
                f"Forbidden tracked RustSec ignores in {path}: {', '.join(ids)}",
                file=sys.stderr,
            )
        print(
            "Upgrade dependencies and validate all gates; do not mask advisories.",
            file=sys.stderr,
        )
        return 1
    print("RustSec policy guard: no tracked advisory suppressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
