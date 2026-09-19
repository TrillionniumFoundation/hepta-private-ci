#!/usr/bin/env python3
"""Select tests from local Cargo dependency ownership, without running builds.

All dependency kinds, cfg targets and optional dependencies are included. Unknown
ownership selects the whole workspace rather than skipping tests. The CLI binds
the plan to the checked-out commit and refuses dirty tracked source. It emits a
plan, not an assertion that any tests passed.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib
from typing import Any, Iterable


class ScopeError(ValueError):
    """Cannot safely establish source ownership or the tested identity."""


def under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def safe_path(path: str) -> str:
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\" in path or "\0" in path:
        raise ScopeError(f"invalid repository-relative path: {path!r}")
    return p.as_posix()


@dataclass(frozen=True)
class Package:
    name: str
    root: str
    manifest: str
    workspace_member: bool


@dataclass
class WorkspaceGraph:
    packages: dict[str, Package]
    consumers: dict[str, set[str]]
    members: set[str]

    @classmethod
    def load(cls, root: Path, tracked: set[str] | None = None) -> WorkspaceGraph:
        root = root.resolve()
        workspace_file = root / "codex-rs/Cargo.toml"

        def relative(path: Path) -> str:
            try:
                return path.resolve().relative_to(root).as_posix()
            except ValueError as exc:
                raise ScopeError(f"local dependency escapes repository: {path}") from exc

        def read(path: Path) -> dict[str, Any]:
            rel = relative(path)
            if tracked is not None and rel not in tracked:
                raise ScopeError(f"manifest is not tracked at the tested commit: {rel}")
            if path.is_symlink():
                raise ScopeError(f"symlinked manifest is unsupported: {rel}")
            try:
                return tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise ScopeError(f"cannot parse {rel}: {exc}") from exc

        workspace_doc = read(workspace_file)
        workspace = workspace_doc.get("workspace")
        if not isinstance(workspace, dict) or not isinstance(workspace.get("members"), list):
            raise ScopeError("codex-rs/Cargo.toml must declare workspace.members")
        workspace_dir = workspace_file.parent
        excludes = workspace.get("exclude", [])
        if not isinstance(excludes, list) or not all(isinstance(x, str) for x in excludes):
            raise ScopeError("invalid workspace.exclude")
        root_dependencies = workspace.get("dependencies", {})
        if not isinstance(root_dependencies, dict):
            raise ScopeError("invalid workspace.dependencies")
        member_manifests: set[str] = set()
        for pattern in workspace["members"]:
            if not isinstance(pattern, str) or not pattern:
                raise ScopeError("invalid workspace member")
            matched = False
            for path in workspace_dir.glob(pattern):
                if not path.is_dir():
                    continue
                member_path = path / "Cargo.toml"
                member_rel = relative(member_path)
                member_dir = path.relative_to(workspace_dir).as_posix()
                if any(fnmatch.fnmatchcase(member_dir, excluded) for excluded in excludes):
                    continue
                if tracked is not None and member_rel not in tracked:
                    if not any(c in pattern for c in "*?["):
                        raise ScopeError(f"untracked workspace member: {member_rel}")
                    continue
                if not member_path.is_file():
                    raise ScopeError(f"workspace member has no manifest: {member_rel}")
                member_manifests.add(member_rel)
                matched = True
            if not matched and not any(c in pattern for c in "*?["):
                raise ScopeError(f"missing workspace member: {pattern}")
        if "package" in workspace_doc:
            member_manifests.add(relative(workspace_file))
        if not member_manifests:
            raise ScopeError("empty workspace member graph")

        documents: dict[str, dict[str, Any]] = {}
        packages: dict[str, Package] = {}
        dependencies: dict[str, set[str]] = {}
        unresolved_names: dict[str, set[str]] = {}
        queue = deque(sorted(member_manifests))
        patch_tables = list(workspace_doc.get("patch", {}).values())
        patch_tables.append(workspace_doc.get("replace", {}))
        for table in patch_tables:
            if not isinstance(table, dict):
                raise ScopeError("invalid root patch/replace table")
            for spec in table.values():
                if isinstance(spec, dict) and "path" in spec:
                    if not isinstance(spec["path"], str):
                        raise ScopeError("non-string patch path")
                    queue.append(relative(workspace_dir / spec["path"] / "Cargo.toml"))
        while queue:
            manifest = queue.popleft()
            if manifest in documents:
                continue
            absolute = root / manifest
            doc = read(absolute)
            package = doc.get("package", {})
            if under(manifest, "codex-rs") and manifest not in member_manifests:
                local_dir = absolute.parent.relative_to(workspace_dir).as_posix()
                if not any(fnmatch.fnmatchcase(local_dir, x) for x in excludes):
                    if "workspace" in doc:
                        raise ScopeError(f"unsupported nested workspace: {manifest}")
                    member_manifests.add(manifest)
            name = package.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", name):
                raise ScopeError(f"missing or unsupported package name: {manifest}")
            packages[manifest] = Package(name, relative(absolute.parent), manifest,
                                         manifest in member_manifests)
            documents[manifest] = doc
            dependencies[manifest] = set()
            unresolved_names[manifest] = set()
            tables: list[dict[str, Any]] = [doc]
            targets = doc.get("target", {})
            if not isinstance(targets, dict):
                raise ScopeError(f"invalid target table: {manifest}")
            tables.extend(targets.values())
            for table in tables:
                if not isinstance(table, dict):
                    raise ScopeError(f"invalid dependency table: {manifest}")
                for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                    entries = table.get(kind, {})
                    if not isinstance(entries, dict):
                        raise ScopeError(f"invalid {kind}: {manifest}")
                    for alias, raw_spec in entries.items():
                        spec = {"version": raw_spec} if isinstance(raw_spec, str) else raw_spec
                        if not isinstance(spec, dict):
                            raise ScopeError(f"invalid dependency {alias}: {manifest}")
                        dependency_root = absolute.parent
                        if spec.get("workspace") is True:
                            if alias not in root_dependencies:
                                raise ScopeError(f"missing inherited dependency {alias}: {manifest}")
                            inherited = root_dependencies[alias]
                            spec = {"version": inherited} if isinstance(inherited, str) else inherited
                            if not isinstance(spec, dict):
                                raise ScopeError(f"invalid inherited dependency {alias}")
                            dependency_root = workspace_dir
                        if "path" in spec:
                            if not isinstance(spec["path"], str):
                                raise ScopeError(f"non-string dependency path: {alias}")
                            dep = relative(dependency_root / spec["path"] / "Cargo.toml")
                            dependencies[manifest].add(dep)
                            queue.append(dep)
                        else:
                            unresolved_names[manifest].add(str(spec.get("package", alias)))

        name_owners: dict[str, set[str]] = {}
        for manifest, package in packages.items():
            name_owners.setdefault(package.name, set()).add(manifest)
        member_names = [packages[m].name for m in member_manifests]
        if len(set(member_names)) != len(member_names):
            raise ScopeError("duplicate workspace package names")
        for manifest, names in unresolved_names.items():
            for name in names:
                dependencies[manifest].update(name_owners.get(name, set()) - {manifest})
        consumers = {manifest: set() for manifest in packages}
        for consumer, deps in dependencies.items():
            for dependency in deps:
                if dependency not in consumers:
                    raise ScopeError(f"unresolved local dependency: {dependency}")
                consumers[dependency].add(consumer)
        return cls(packages, consumers, member_manifests)

    def owners(self, path: str) -> set[str]:
        matches = [p for p in self.packages.values() if under(path, p.root)]
        if not matches:
            return set()
        longest = max(len(p.root) for p in matches)
        return {p.manifest for p in matches if len(p.root) == longest}

    def reverse_closure(self, roots: Iterable[str]) -> set[str]:
        selected = set(roots)
        queue = deque(sorted(selected))
        while queue:
            for consumer in sorted(self.consumers[queue.popleft()]):
                if consumer not in selected:
                    selected.add(consumer)
                    queue.append(consumer)
        return selected & self.members

    def member_names(self, manifests: Iterable[str] | None = None) -> list[str]:
        return sorted(self.packages[m].name for m in (self.members if manifests is None else manifests))


@dataclass(frozen=True)
class TestPlan:
    changed_paths: list[str]
    rust_packages: list[str]
    full_workspace: bool
    engineering: bool
    os_evidence: bool
    ui_browser: bool
    ui_native: bool
    source_owner: bool
    reasons: list[str]

    def outputs(self) -> dict[str, str]:
        return {
            "rust_packages": json.dumps(self.rust_packages, separators=(",", ":")),
            "rust_required": str(bool(self.rust_packages)).lower(),
            "full_workspace": str(self.full_workspace).lower(),
            "engineering": str(self.engineering).lower(),
            "os_evidence": str(self.os_evidence).lower(),
            "ui_browser": str(self.ui_browser).lower(),
            "ui_native": str(self.ui_native).lower(),
            "source_owner": str(self.source_owner).lower(),
        }


GLOBAL_FILES = {
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "justfile", "codex-rs/justfile",
    "Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml",
    "codex-rs/rust-toolchain", "codex-rs/rust-toolchain.toml",
    "scripts/hepta_ci_scope.py", "scripts/hepta_ci_exec.py", "scripts/hepta_ci_v8.py",
    "scripts/hepta_ci_run.py", "scripts/test_hepta_ci_scope.py",
    "scripts/test_hepta_ci_run.py", "scripts/verify_cargo_lock.py",
    ".github/workflows/hepta-consolidated-source.yml",
}
GLOBAL_PREFIXES = (
    "codex-rs/core", "codex-rs/common", "codex-rs/protocol", ".cargo",
    "codex-rs/.cargo", ".github/actions", "patches", "third_party", "vendor",
)
PROSE_SUFFIXES = {".md", ".rst", ".txt", ".png", ".jpg", ".svg"}


def select(graph: WorkspaceGraph, paths: Iterable[str], *, unknown_diff: bool = False) -> TestPlan:
    changed = sorted({safe_path(path) for path in paths})
    roots: set[str] = set()
    full = unknown_diff
    engineering = os_evidence = browser = native = unknown_diff
    source_owner = unknown_diff
    reasons = ["base commit unavailable: conservative full selection"] if unknown_diff else []
    for path in changed:
        filename = PurePosixPath(path).name
        if (path in GLOBAL_FILES or any(under(path, p) for p in GLOBAL_PREFIXES)
                or (under(path, "codex-rs") and filename in {"Cargo.toml", "build.rs"})):
            full = engineering = os_evidence = browser = native = source_owner = True
            reasons.append(f"shared source/build configuration: {path}")
            continue
        if under(path, "tools/hepta-engineering-control"):
            engineering = source_owner = True
        elif under(path, "tools/hepta-os-evidence"):
            os_evidence = source_owner = True
        elif under(path, "apps/hepta-browser"):
            browser = source_owner = True
        elif under(path, "apps/hepta-native"):
            native = source_owner = True
        elif filename in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
            full = engineering = os_evidence = browser = native = source_owner = True
            reasons.append(f"shared JS build configuration: {path}")
        elif owners := graph.owners(path):
            roots.update(owners)
            source_owner = True
        elif under(path, "docs") and PurePosixPath(path).suffix in PROSE_SUFFIXES:
            pass
        elif "/" not in path and (PurePosixPath(path).suffix in PROSE_SUFFIXES
                                  or filename in {"LICENSE", "NOTICE"}):
            pass
        else:
            full = engineering = os_evidence = browser = native = source_owner = True
            reasons.append(f"unclassified source: {path}")
    names = graph.member_names() if full else graph.member_names(graph.reverse_closure(roots))
    if roots and not full:
        reasons.append("changed packages plus transitive reverse dependencies (all kinds/targets/features)")
    return TestPlan(changed, names, full, engineering, os_evidence, browser, native,
                    source_owner, sorted(set(reasons)))


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def collect(root: Path, base: str, tested: str) -> tuple[list[str], bool, set[str]]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", tested):
        raise ScopeError("tested identity must be a full commit hash")
    actual = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    if actual.lower() != tested.lower():
        raise ScopeError("checked-out HEAD does not equal tested identity")
    for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if git(root, *args, check=False).returncode != 0:
            raise ScopeError("tracked source is dirty")
    tracked = set(git(root, "ls-files", "-z").stdout.decode("utf-8").rstrip("\0").split("\0"))
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base) or set(base) == {"0"}:
        return [], True, tracked
    if git(root, "cat-file", "-e", base + "^{commit}", check=False).returncode != 0:
        return [], True, tracked
    raw = git(root, "diff", "--name-only", "-z", "--no-renames", base, tested, "--").stdout
    return [p for p in raw.decode("utf-8").split("\0") if p], False, tracked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", required=True)
    parser.add_argument("--tested", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        paths, unknown, tracked = collect(args.root, args.base, args.tested)
        plan = select(WorkspaceGraph.load(args.root, tracked), paths, unknown_diff=unknown)
        document = {"schema": "hepta.ci-test-plan.v1", "tested_commit": args.tested,
                    "tested_tree": git(args.root, "rev-parse", "HEAD^{tree}").stdout.decode().strip(),
                    "comparison_base": args.base, **asdict(plan)}
        encoded = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                for key, value in plan.outputs().items():
                    stream.write(f"{key}={value}\n")
        print(encoded, end="")
        return 0
    except (ScopeError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"HEPTA_SCOPE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
