#!/usr/bin/env python3
"""Fail-closed canonical path guard for Lane B source-evidence bindings."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"


class Invalid(ValueError):
    pass


def need(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        need(key not in out, f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path}: {exc}") from exc
    need(isinstance(value, dict), f"{path}: expected object")
    return value


def canonical_path(root: Path, value: Any, label: str, *, require_file: bool | None) -> Path:
    need(
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and ":" not in value
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        f"{label}: invalid repository-relative path",
    )
    root = root.resolve()
    path = root
    try:
        for part in value.split("/"):
            path = path / part
            need(not path.is_symlink(), f"{label}: symlink binding {value!r}")
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise Invalid(f"{label}: unresolvable path") from exc
    need(
        resolved.is_relative_to(root)
        and resolved.relative_to(root).as_posix() == value,
        f"{label}: aliased path {value!r}",
    )
    if require_file is True:
        exists = path.is_file()
    elif require_file is False:
        exists = path.is_dir()
    else:
        exists = path.is_file() or path.is_dir()
    need(exists, f"{label}: missing path {value}")
    return path


def inside(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def verify_anchor(
    root: Path,
    module: str,
    roots: dict[str, list[str]],
    anchor: dict[str, Any],
    *,
    owner: bool,
) -> None:
    need(isinstance(anchor, dict), f"{module}: anchor must be object")
    need(set(anchor) >= {"role", "path", "symbol", "buildTarget"}, f"{module}: anchor")
    path = anchor["path"]
    source = canonical_path(root, path, f"{module}: source", require_file=True)
    if owner:
        need(inside(path, roots[module]), f"{module}: owner-root escape {path}")
    else:
        delegated_owner = anchor.get("ownerModule")
        need(
            isinstance(delegated_owner, str) and delegated_owner in roots,
            f"{module}: delegated owner",
        )
        need(inside(path, roots[delegated_owner]), f"{module}: delegate-root escape {path}")
    symbol = anchor["symbol"]
    target = anchor["buildTarget"]
    need(isinstance(symbol, str) and bool(symbol.strip()), f"{module}: invalid symbol")
    need(isinstance(target, str) and bool(target.strip()), f"{module}: build target")
    need(symbol in source.read_text(encoding="utf-8"), f"{module}: missing symbol {symbol!r}")


def verify(root: Path = ROOT) -> int:
    truth = load(TRUTH if root == ROOT else root / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json")
    entries = truth.get("modules")
    need(isinstance(entries, list) and entries, "module index")

    maps: dict[str, dict[str, Any]] = {}
    roots: dict[str, list[str]] = {}
    for entry in entries:
        need(isinstance(entry, dict), "module index entry")
        module = entry.get("module")
        map_path = entry.get("mapPath")
        need(isinstance(module, str) and bool(module), "module identity")
        path = canonical_path(root, map_path, f"{module}: map", require_file=True)
        row = load(path)
        need(row.get("module") == module, f"{module}: map identity")
        resolved_roots = row.get("resolvedRoots")
        need(
            isinstance(resolved_roots, list)
            and resolved_roots
            and all(isinstance(item, str) and item for item in resolved_roots),
            f"{module}: resolved roots",
        )
        for owner_root in resolved_roots:
            canonical_path(root, owner_root, f"{module}: owner root", require_file=None)
        maps[module] = row
        roots[module] = resolved_roots

    operations = tests = delegates = 0
    for module, row in maps.items():
        items = row.get("operations")
        need(isinstance(items, list) and items, f"{module}: operations")
        for item in items:
            operations += 1
            need(isinstance(item, dict), f"{module}: operation")
            anchor = item.get("ownerEntrypoint") or {
                "role": "owner_entrypoint",
                "path": item.get("sourcePath"),
                "symbol": item.get("nativeSymbol"),
                "buildTarget": item.get("buildTarget", "canonical-v3"),
            }
            verify_anchor(root, module, roots, anchor, owner=True)
            for delegate in item.get("delegatedCallees", []):
                delegates += 1
                verify_anchor(root, module, roots, delegate, owner=False)
            bound_tests = item.get("tests")
            need(isinstance(bound_tests, list) and bound_tests, f"{module}: tests")
            for test in bound_tests:
                tests += 1
                need(isinstance(test, dict), f"{module}: test binding")
                canonical_path(root, test.get("path"), f"{module}: test", require_file=True)
                command = test.get("command")
                need(isinstance(command, str) and bool(command.strip()), f"{module}: test command")

    print(json.dumps({
        "status": "PASS_HEPTA_LANE_B_CANONICAL_PATH_GUARD",
        "modules": len(maps),
        "operations": operations,
        "delegates": delegates,
        "testBindings": tests,
    }, sort_keys=True))
    return 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "repo"
        owned = root / "owned"
        foreign = root / "foreign"
        owned.mkdir(parents=True)
        foreign.mkdir()
        source = owned / "source.rs"
        source.write_text("pub fn run() {}\n", encoding="utf-8")
        foreign_source = foreign / "source.rs"
        foreign_source.write_text("pub fn run() {}\n", encoding="utf-8")
        need(canonical_path(root, "owned/source.rs", "fixture", require_file=True) == source, "canonical fixture")
        need(
            canonical_path(root, "owned/source.rs", "fixture root", require_file=None) == source,
            "file-backed root fixture",
        )
        need(
            canonical_path(root, "owned", "fixture root", require_file=None) == owned,
            "directory-backed root fixture",
        )
        for bad in (
            "owned/../foreign/source.rs",
            "owned/./source.rs",
            "owned//source.rs",
            "../source.rs",
            "owned\\source.rs",
            "C:owned/source.rs",
            "owned/source.rs:stream",
            "owned/\nsource.rs",
        ):
            try:
                canonical_path(root, bad, "fixture", require_file=True)
            except Invalid:
                pass
            else:
                raise Invalid(f"accepted unsafe path {bad!r}")
        link = owned / "link.rs"
        try:
            link.symlink_to(foreign_source)
        except OSError:
            pass
        else:
            try:
                canonical_path(root, "owned/link.rs", "fixture", require_file=True)
            except Invalid:
                pass
            else:
                raise Invalid("accepted symlink binding")
    print(json.dumps({"status": "PASS_HEPTA_LANE_B_CANONICAL_PATH_GUARD_SELF_TEST"}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"))
    command = parser.parse_args().command
    return self_test() if command == "self-test" else verify()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_CANONICAL_PATH_GUARD: {exc}") from exc
