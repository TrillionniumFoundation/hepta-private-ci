#!/usr/bin/env python3
"""Reject Rust source files that are unreachable from a crate root.

The check follows ordinary ``mod name;`` declarations and explicit
``#[path = "..."] mod name;`` declarations recursively. Conditional modules are
still part of the declared source graph and therefore count as reachable.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MOD_RE = re.compile(
    r"(?:#\s*\[\s*path\s*=\s*\"(?P<path>[^\"]+)\"\s*\]\s*)?"
    r"(?:pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;",
    re.MULTILINE,
)


def resolve_module(source: Path, name: str, explicit: str | None) -> Path:
    if explicit is not None:
        candidate = (source.parent / explicit).resolve()
        if not candidate.is_file():
            raise SystemExit(f"declared Rust module path does not exist: {candidate}")
        return candidate

    sibling = source.parent / f"{name}.rs"
    nested = source.parent / name / "mod.rs"
    matches = [candidate.resolve() for candidate in (sibling, nested) if candidate.is_file()]
    if len(matches) != 1:
        raise SystemExit(
            f"module {name!r} from {source} resolves to {len(matches)} files; expected one"
        )
    return matches[0]


def reachable_sources(root: Path) -> set[Path]:
    entry = (root / "lib.rs").resolve()
    if not entry.is_file():
        entry = (root / "main.rs").resolve()
    if not entry.is_file():
        raise SystemExit(f"no lib.rs or main.rs under Rust source root: {root}")

    reachable: set[Path] = set()
    pending = [entry]
    while pending:
        source = pending.pop()
        if source in reachable:
            continue
        reachable.add(source)
        text = source.read_text(encoding="utf-8")
        for match in MOD_RE.finditer(text):
            child = resolve_module(source, match.group("name"), match.group("path"))
            if child not in reachable:
                pending.append(child)
    return reachable


def check(root: Path) -> dict[str, object]:
    root = root.resolve()
    declared = reachable_sources(root)
    actual = {path.resolve() for path in root.rglob("*.rs") if path.is_file()}
    orphaned = sorted(path.relative_to(root).as_posix() for path in actual - declared)
    if orphaned:
        raise SystemExit(
            "unreachable Rust source files under "
            f"{root}: " + ", ".join(orphaned)
        )
    return {
        "root": root.as_posix(),
        "reachable": sorted(path.relative_to(root).as_posix() for path in declared),
        "sourceCount": len(actual),
        "orphaned": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        default=[Path("codex-rs/hepta-cognitive-store/src")],
    )
    args = parser.parse_args()
    receipts = [check(root) for root in args.roots]
    print(json.dumps({"schema": "hepta.rust-module-inventory.v1", "roots": receipts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
