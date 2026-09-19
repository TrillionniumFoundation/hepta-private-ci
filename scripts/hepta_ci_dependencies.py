#!/usr/bin/env python3
"""Select Cargo owners and reverse dependents from BOTH exact Git revisions.

No build script or network resolver runs while planning. All normal, build,
optional, renamed and target-specific dependencies are included conservatively.
Dev dependencies select their direct consumer's tests, but do not make that
consumer's downstream production crates depend on its test-only dependencies.
Unknown/shared inputs select the entire workspace. An absent or invalid base
never means 'no tests'. The plan is execution input, not a qualification receipt.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import posixpath
import re
import subprocess
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

OID = re.compile(r"[0-9a-f]{40}\Z")
WORKSPACE = "codex-rs"
SHARED = {"Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml",
          "justfile", "build.rs", "MODULE.bazel", "MODULE.bazel.lock"}


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args],
                          check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


@dataclass(frozen=True)
class Graph:
    owners: dict[str, str]
    # (dependency, consumer, test-only): preserve dev-edge semantics.
    edges: frozenset[tuple[str, str, bool]]
    members: frozenset[str] | None = None
    conservative: bool = False

    @property
    def targets(self) -> set[str]:
        return set(self.owners.values()) if self.members is None else set(self.members)


def matches(path: str, pattern: str) -> bool:
    """Cargo-style path globs: '*' does not cross a directory separator."""
    parts, patterns = tuple(path.split("/")), tuple(pattern.split("/"))

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def graph(root: Path, revision: str) -> Graph:
    if not OID.fullmatch(revision):
        raise ValueError("revision must be an exact Git SHA")
    paths = set(git(root, "ls-tree", "-r", "--name-only", "-z", revision).decode("utf-8").split("\0"))

    @lru_cache(maxsize=None)
    def load(path: str) -> dict:
        return tomllib.loads(git(root, "show", f"{revision}:{path}").decode("utf-8"))

    root_manifest = load(f"{WORKSPACE}/Cargo.toml")
    workspace = root_manifest["workspace"]
    available = {posixpath.dirname(p) for p in paths if p.endswith("/Cargo.toml")}
    excluded = [posixpath.normpath(f"{WORKSPACE}/{p}") for p in workspace.get("exclude", [])]
    members: set[str] = set()
    for member in workspace.get("members", []):
        pattern = posixpath.normpath(f"{WORKSPACE}/{member}")
        matched = {p for p in available if matches(p, pattern)}
        if not matched:
            raise ValueError(f"workspace member has no manifest: {member}")
        members.update(matched)
    members = {p for p in members if not any(matches(p, e) for e in excluded)}
    if "package" in root_manifest:
        members.add(WORKSPACE)
    inherited = workspace.get("dependencies", {})
    manifests: dict[str, dict] = {}
    local_edges: set[tuple[str, str, bool]] = set()
    patch_paths: dict[str, set[str]] = {}
    for table in root_manifest.get("patch", {}).values():
        for alias, declaration in table.items():
            if isinstance(declaration, dict) and "path" in declaration:
                name = declaration.get("package", alias)
                patch_paths.setdefault(name, set()).add(
                    posixpath.normpath(f"{WORKSPACE}/{declaration['path']}")
                )
    pending = list(members)
    # Cargo automatically includes reachable path dependencies inside the
    # workspace, including test-support crates absent from the explicit list.
    while pending:
        folder = pending.pop()
        if folder in manifests:
            continue
        doc = load(f"{folder}/Cargo.toml")
        manifests[folder] = doc
        for section in [doc, *doc.get("target", {}).values()]:
            for kind in ("dependencies", "build-dependencies", "dev-dependencies"):
                for alias, declaration in section.get(kind, {}).items():
                    if not isinstance(declaration, dict):
                        declaration = {"version": declaration}
                    dependency_root = folder
                    if declaration.get("workspace") is True:
                        if alias not in inherited:
                            raise ValueError(f"unknown workspace dependency {alias}")
                        declaration = inherited[alias]
                        dependency_root = WORKSPACE
                        if not isinstance(declaration, dict):
                            declaration = {"version": declaration}
                    name = declaration.get("package", alias)
                    direct = "path" in declaration
                    targets = ({posixpath.normpath(f"{dependency_root}/{declaration['path']}")}
                               if direct else patch_paths.get(name, set()))
                    # Include every possible local patch, regardless of source
                    # or version eligibility. This may over-select, never omit
                    # a reverse consumer when the lock resolver chooses a patch.
                    for target in targets:
                        if target not in available:
                            raise ValueError(f"unresolved local dependency: {target}")
                        target_doc = load(f"{target}/Cargo.toml")
                        if name != target_doc["package"]["name"]:
                            raise ValueError(f"local dependency name mismatch: {alias}")
                        local_edges.add((target, folder, kind == "dev-dependencies"))
                        pending.append(target)
                        if (direct and target.startswith(WORKSPACE + "/")
                                and not any(matches(target, e) for e in excluded)
                                and "workspace" not in target_doc):
                            members.add(target)
    owners = {p: doc["package"]["name"] for p, doc in manifests.items()}
    if not owners or len(set(owners.values())) != len(owners):
        raise ValueError("empty workspace or duplicate package names")
    if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", n) for n in owners.values()):
        raise ValueError("invalid Cargo package name")
    edges = frozenset((owners[d], owners[c], dev) for d, c, dev in local_edges)
    # Deprecated version-qualified replacements have different resolver
    # semantics. Keep the conservative escape hatch instead of guessing.
    conservative = bool(root_manifest.get("replace"))
    return Graph(owners, edges, frozenset(owners[p] for p in members), conservative)


def select_packages(paths: Iterable[str], before: Graph, after: Graph) -> dict:
    changed = set()
    reasons = set()
    owners = before.owners | after.owners
    # Preserve old owners on package renames, including same-directory renames.
    for path in paths:
        parts = path.split("/")
        if not path or path.startswith("/") or ".." in parts or "\\" in path or "\0" in path:
            raise ValueError(f"invalid repository path: {path!r}")
        if path in SHARED or path in {f"{WORKSPACE}/{p}" for p in SHARED}:
            reasons.add(f"shared build input: {path}")
            continue
        if path.startswith((".cargo/", f"{WORKSPACE}/.cargo/", ".github/", "scripts/")):
            reasons.add(f"shared CI input: {path}")
            continue
        matched = [p for p in owners if path.startswith(p + "/")]
        if not matched:
            reasons.add(f"unowned input: {path}")
            continue
        folder = max(matched, key=len)
        for mapping in (before.owners, after.owners):
            if folder in mapping:
                changed.add(mapping[folder])
        if path.endswith("/build.rs"):
            reasons.add(f"build script: {path}")
    current = after.targets
    if before.conservative or after.conservative:
        reasons.add("local registry override; full resolver fallback")
    if reasons:
        return {"packages": sorted(current), "full_workspace": True,
                "changed_packages": sorted(changed), "reasons": sorted(reasons)}
    # Build reverse adjacency once. Re-scanning every edge for every reached
    # package makes a long dependency chain quadratic in workspace size.
    # Keep dev and production edges distinct, including across both revisions.
    reverse: dict[str, list[tuple[str, bool]]] = {}
    for source, consumer, dev_only in before.edges | after.edges:
        reverse.setdefault(source, []).append((consumer, dev_only))
    affected = set(changed)
    pending = list(changed)
    tests = set()
    while pending:
        dependency = pending.pop()
        for consumer, dev_only in reverse.get(dependency, ()):
            tests.add(consumer)
            if not dev_only and consumer not in affected:
                affected.add(consumer)
                pending.append(consumer)
    return {"packages": sorted((affected | tests) & current), "full_workspace": False,
            "changed_packages": sorted(changed), "reasons": []}


def plan(root: Path, base: str | None, tested: str) -> dict:
    after = graph(root, tested)
    if not base or not OID.fullmatch(base) or base == "0" * 40:
        return {"packages": sorted(after.targets), "full_workspace": True,
                "changed_packages": [], "reasons": ["no exact base"]}
    try:
        before = graph(root, base)
        paths = git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only",
                    "--no-renames", "-z", base, tested, "--")
    except (subprocess.CalledProcessError, ValueError, KeyError, tomllib.TOMLDecodeError):
        return {"packages": sorted(after.targets), "full_workspace": True,
                "changed_packages": [], "reasons": ["base graph unavailable; full fallback"]}
    return select_packages((p.decode("utf-8") for p in paths.split(b"\0") if p), before, after)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--tested", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", action="store_true", help="execute the plan with just test --locked")
    args = parser.parse_args()
    if not OID.fullmatch(args.tested):
        parser.error("--tested must be an exact 40-character SHA")
    if git(args.root, "rev-parse", "HEAD").decode().strip() != args.tested:
        parser.error("checkout differs from --tested")
    git(args.root, "diff", "--no-ext-diff", "--quiet", "HEAD", "--")
    selected = plan(args.root, args.base, args.tested)
    payload = {"tested_sha": args.tested, "base_sha": args.base, **selected}
    text = json.dumps(payload, sort_keys=True) + "\n"
    print(text, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.run and selected["packages"]:
        command = ["just", "test", "--locked"]
        if selected["full_workspace"]:
            command.append("--workspace")
        if not selected["full_workspace"]:
            for package in selected["packages"]:
                command.extend(["-p", package])
        subprocess.run(command, cwd=args.root / WORKSPACE, check=True)
        git(args.root, "diff", "--no-ext-diff", "--quiet", "HEAD", "--")


if __name__ == "__main__":
    main()
