#!/usr/bin/env python3
"""Fail when tracked Hepta Rust source is not reachable from any Cargo target.

Cargo metadata supplies the authoritative target roots.  This scanner follows
external ``mod`` declarations, ``#[path]`` attributes and literal ``include!``
files across the whole workspace, so shared integration-test support and
cross-package fixtures are not mistaken for orphan source.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

MODULE_RE = re.compile(
    r"(?ms)(?P<attrs>(?:\s*#\s*\[[^\]]*\]\s*)*)"
    r"(?:pub(?:\([^)]*\))?\s+)?mod\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;"
)
PATH_RE = re.compile(r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]')
INCLUDE_RE = re.compile(r'\binclude!\s*\(\s*"([^"]+\.rs)"\s*\)')
SOURCE_DIRS = ("src", "tests", "examples", "benches")
EXCLUDED_PARTS = frozenset({"target", "fixtures", "testdata", "test_data", "corpus"})


def cargo_metadata(root: Path, manifest: Path) -> dict[str, Any]:
    command = [
        "cargo",
        "metadata",
        "--locked",
        "--no-deps",
        "--format-version=1",
        "--manifest-path",
        str(root / manifest),
    ]
    return json.loads(subprocess.check_output(command, cwd=root, text=True))


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def hepta_packages(root: Path, metadata: dict[str, Any]) -> list[tuple[str, Path]]:
    cargo_root = (root / "codex-rs").resolve()
    packages: list[tuple[str, Path]] = []
    for package in metadata.get("packages", []):
        name = package.get("name")
        manifest = Path(package.get("manifest_path", "")).resolve()
        if (
            isinstance(name, str)
            and name.startswith("codex-hepta-")
            and _inside(manifest, cargo_root)
        ):
            packages.append((name, manifest.parent))
    return sorted(packages)


def target_roots(metadata: dict[str, Any]) -> set[Path]:
    roots: set[Path] = set()
    for package in metadata.get("packages", []):
        for target in package.get("targets", []):
            source = target.get("src_path")
            if isinstance(source, str):
                roots.add(Path(source).resolve())
    return roots


def _module_base(source: Path, crate_roots: set[Path]) -> Path:
    if source in crate_roots or source.name in {"lib.rs", "main.rs", "mod.rs"}:
        return source.parent
    return source.parent / source.stem


def direct_children(source: Path, crate_roots: set[Path]) -> list[Path]:
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    children: list[Path] = []
    for match in INCLUDE_RE.finditer(text):
        candidate = (source.parent / match.group(1)).resolve()
        if candidate.is_file():
            children.append(candidate)
    base = _module_base(source, crate_roots)
    for match in MODULE_RE.finditer(text):
        path_match = PATH_RE.search(match.group("attrs") or "")
        if path_match:
            candidate = (source.parent / path_match.group(1)).resolve()
            if candidate.is_file():
                children.append(candidate)
            continue
        name = match.group("name")
        flat = (base / f"{name}.rs").resolve()
        nested = (base / name / "mod.rs").resolve()
        if flat.is_file():
            children.append(flat)
        elif nested.is_file():
            children.append(nested)
    return children


def reachable_sources(crate_roots: set[Path]) -> set[Path]:
    reachable: set[Path] = set()
    pending: deque[Path] = deque(sorted(crate_roots))
    while pending:
        source = pending.popleft()
        if source in reachable or not source.is_file():
            continue
        reachable.add(source)
        for child in direct_children(source, crate_roots):
            if child not in reachable:
                pending.append(child)
    return reachable


def tracked_candidates(root: Path, packages: list[tuple[str, Path]]) -> dict[Path, str]:
    tracked = {
        (root / value).resolve()
        for value in subprocess.check_output(
            ["git", "ls-files", "-z", "--", "codex-rs"], cwd=root
        )
        .decode("utf-8")
        .split("\0")
        if value.endswith(".rs")
    }
    result: dict[Path, str] = {}
    for name, package_root in packages:
        for directory in SOURCE_DIRS:
            source_root = package_root / directory
            if not source_root.is_dir():
                continue
            for source in source_root.rglob("*.rs"):
                resolved = source.resolve()
                relative = source.relative_to(package_root)
                if resolved not in tracked or EXCLUDED_PARTS.intersection(relative.parts):
                    continue
                result[resolved] = name
    return result


def scan(root: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    packages = hepta_packages(root, metadata)
    roots = target_roots(metadata)
    reachable = reachable_sources(roots)
    candidates = tracked_candidates(root, packages)
    unreachable = [
        {
            "package": candidates[source],
            "path": source.relative_to(root).as_posix(),
        }
        for source in sorted(candidates)
        if source not in reachable
    ]
    return {
        "schema": "hepta.rust-source-reachability.v1",
        "packageCount": len(packages),
        "targetRootCount": len(roots),
        "candidateSourceCount": len(candidates),
        "reachableSourceCount": sum(source in reachable for source in candidates),
        "unreachableSources": unreachable,
        "status": "aligned" if not unreachable else "orphan_source",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=Path("codex-rs/Cargo.toml"))
    parser.add_argument("--metadata-json", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        metadata = (
            json.loads(args.metadata_json.read_text(encoding="utf-8"))
            if args.metadata_json
            else cargo_metadata(args.root, args.manifest)
        )
        report = scan(args.root, metadata)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"FAIL_HEPTA_RUST_REACHABILITY: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if args.strict and report["status"] != "aligned" else 0


if __name__ == "__main__":
    raise SystemExit(main())
