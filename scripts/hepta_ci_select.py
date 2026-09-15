#!/usr/bin/env python3
"""Select affected Rust owner packages; uncertainty always falls back to all."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MANIFEST = ROOT / "codex-rs" / "Cargo.toml"

FULL_FALLBACK_PATHS = {
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "rust-toolchain.toml",
    "rust-toolchain",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/rust-toolchain",
    "justfile",
    "scripts/just-shell.py",
    "scripts/hepta_ci_select.py",
    "scripts/hepta_ci_exec.py",
    "scripts/hepta_ci_v8.py",
}
FULL_FALLBACK_PREFIXES = (
    "codex-rs/.cargo/",
    ".cargo/",
    ".github/actions/",
    ".github/workflows/",
    "patches/",
)


class SelectionError(RuntimeError):
    pass


def _git(*args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise SelectionError(process.stderr.decode("utf-8", errors="replace").strip() or "git selection query failed")
    return process.stdout.decode("utf-8")


def changed_paths(base: str, head: str) -> list[str]:
    """Include both sides of moves and every deletion, without pathname quoting.

    Disabling rename detection represents a move as delete + add. This selects
    both the old owner's consumers and the new owner's consumers. NUL framing
    preserves spaces, tabs, Unicode and newlines in legitimate Git filenames.
    """
    if not base or not head:
        raise SelectionError("base and head are required")
    commits = []
    for ref in (base, head):
        commit = _git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
            raise SelectionError("invalid resolved commit")
        commits.append(commit)
    output = _git("diff", "--no-renames", "--name-only", "-z", *commits, "--")
    return [path for path in output.split("\0") if path]


def cargo_metadata() -> dict[str, Any]:
    process = subprocess.run(
        [
            "cargo", "metadata", "--format-version=1", "--no-deps",
            "--manifest-path", str(WORKSPACE_MANIFEST),
        ],
        cwd=ROOT / "codex-rs",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise SelectionError(process.stderr.strip() or "cargo metadata failed")
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise SelectionError(f"invalid cargo metadata: {error}") from error
    if not isinstance(value, dict):
        raise SelectionError("cargo metadata is not an object")
    return value


def _relative_manifest_dir(manifest_path: str) -> PurePosixPath:
    path = Path(manifest_path).resolve().parent
    try:
        relative = path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise SelectionError(f"workspace package escapes repository: {path}") from error
    return PurePosixPath(relative.as_posix())


def _path_dependency_names(package: dict[str, Any]) -> set[str]:
    names = set()
    for dependency in package.get("dependencies", []):
        if not isinstance(dependency, dict):
            raise SelectionError("cargo package dependency is not an object")
        if dependency.get("path") is not None:
            name = dependency.get("name")
            if not isinstance(name, str) or not name:
                raise SelectionError("path dependency has no package name")
            names.add(name)
    return names


def select_packages(
    paths: Iterable[str],
    metadata: dict[str, Any],
    candidates: Iterable[str],
) -> dict[str, Any]:
    candidate_order = list(dict.fromkeys(candidates))
    candidate_set = set(candidate_order)
    if not candidate_order or any(
        not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None
        for name in candidate_order
    ):
        raise SelectionError("valid candidate package names are required")
    normalized = []
    for raw in paths:
        if not isinstance(raw, str) or not raw or "\0" in raw:
            raise SelectionError("invalid changed path")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise SelectionError("changed path escapes repository")
        normalized.append(path.as_posix())
    if any(
        path in FULL_FALLBACK_PATHS
        or any(path.startswith(prefix) for prefix in FULL_FALLBACK_PREFIXES)
        for path in normalized
    ):
        return {
            "required": True, "full": True, "packages": candidate_order,
            "reason": "workspace_or_ci_control_changed",
        }

    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SelectionError("cargo metadata contains no packages")
    workspace_members = set(metadata.get("workspace_members", []))
    by_name: dict[str, dict[str, Any]] = {}
    directories: list[tuple[PurePosixPath, str]] = []
    reverse: dict[str, set[str]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise SelectionError("cargo metadata package is not an object")
        package_id = package.get("id")
        name = package.get("name")
        manifest_path = package.get("manifest_path")
        if not isinstance(package_id, str) or not isinstance(name, str) or not isinstance(manifest_path, str):
            raise SelectionError("cargo metadata package identity is incomplete")
        if workspace_members and package_id not in workspace_members:
            continue
        if name in by_name:
            raise SelectionError(f"duplicate workspace package name: {name}")
        by_name[name] = package
        directories.append((_relative_manifest_dir(manifest_path), name))
        reverse.setdefault(name, set())

    if not candidate_set.issubset(by_name):
        missing = sorted(candidate_set - set(by_name))
        raise SelectionError("candidate packages missing from workspace: " + ", ".join(missing))

    for name, package in by_name.items():
        for dependency in _path_dependency_names(package):
            if dependency in by_name:
                reverse.setdefault(dependency, set()).add(name)

    directories.sort(key=lambda item: len(item[0].parts), reverse=True)
    changed_packages: set[str] = set()
    for raw_path in normalized:
        path = PurePosixPath(raw_path)
        matched = None
        for directory, name in directories:
            if path == directory or directory in path.parents:
                matched = name
                break
        if matched is not None:
            changed_packages.add(matched)
        elif raw_path == "codex-rs" or raw_path.startswith("codex-rs/"):
            return {
                "required": True, "full": True, "packages": candidate_order,
                "reason": "unknown_workspace_path",
            }

    if not changed_packages:
        return {
            "required": False, "full": False, "packages": [],
            "reason": "no_rust_workspace_change",
        }

    affected = set(changed_packages)
    frontier = list(changed_packages)
    while frontier:
        dependency = frontier.pop()
        for dependent in reverse.get(dependency, ()):
            if dependent not in affected:
                affected.add(dependent)
                frontier.append(dependent)
    selected = [name for name in candidate_order if name in affected]
    return {
        "required": bool(selected), "full": False, "packages": selected,
        "reason": "dependency_closure" if selected else "changed_packages_outside_owner_set",
    }


def _emit(selection: dict[str, Any], github_output: Path | None) -> None:
    print(json.dumps(selection, sort_keys=True))
    if github_output is None:
        return
    packages = " ".join(selection["packages"])
    with github_output.open("a", encoding="utf-8") as stream:
        stream.write(f"required={'true' if selection['required'] else 'false'}\n")
        stream.write(f"full={'true' if selection['full'] else 'false'}\n")
        stream.write(f"packages={packages}\n")
        stream.write(f"reason={selection['reason']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--packages", nargs="+", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if any(re.fullmatch(r"[A-Za-z0-9_-]+", name) is None for name in args.packages):
        parser.error("invalid package name")
    try:
        paths = changed_paths(args.base, args.head)
        metadata = cargo_metadata()
        selection = select_packages(paths, metadata, args.packages)
    except (OSError, UnicodeError, SelectionError, subprocess.SubprocessError) as error:
        selection = {
            "required": True, "full": True,
            "packages": list(dict.fromkeys(args.packages)),
            "reason": f"full_fallback:{type(error).__name__}",
        }
        print(f"dependency selection failed closed: {error}", file=sys.stderr)
    _emit(selection, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
