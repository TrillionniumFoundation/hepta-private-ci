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
SHARED = {
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
    "justfile",
    "build.rs",
    "MODULE.bazel",
    "MODULE.bazel.lock",
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


@dataclass(frozen=True)
class Graph:
    owners: dict[str, str]
    # (dependency, consumer, test-only): preserve dev-edge semantics.
    edges: frozenset[tuple[str, str, bool]]
    members: frozenset[str] | None = None
    conservative: bool = False
    # Exact non-Cargo inputs embedded by Rust macros in either revision.
    external_inputs: frozenset[tuple[str, str]] = frozenset()
    opaque_input_consumers: frozenset[str] = frozenset()

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
        return (
            i < len(parts)
            and fnmatch.fnmatchcase(parts[i], patterns[j])
            and match(i + 1, j + 1)
        )

    return match(0, 0)


# Match the same presentation-only paths used by the outer scope selector.
# Embedded inputs are accounted for FIRST, even when their suffix is .md.
PRESENTATION_INPUTS = frozenset(
    {
        "README.md",
        "CONTRIBUTING.md",
        "docs/modules/SOURCE_BINDINGS.json",
        "docs/modules/MODULE_DOCS.json",
    }
)
INCLUDE = re.compile(r"\b(?P<macro>include(?:_str|_bytes)?)\s*!\s*[({\[]")
INCLUDE_LITERAL = re.compile(
    r'(?:r(?P<hashes>#{0,16})"(?P<raw>.*?)"(?P=hashes)|"(?P<plain>(?:\\.|[^"\\])*)")',
    re.S,
)


MODULE_PATH = re.compile(r"#\s*\[\s*path\s*=")
OUTLINED_MODULE = re.compile(r"\bmod\s+(?:r#)?([A-Za-z_][A-Za-z0-9_]*)\s*;")
INLINE_MODULE = re.compile(r"\bmod\s+(?:r#)?[A-Za-z_][A-Za-z0-9_]*\s*\{")


def module_source_inputs(path: str, text: str, tracked: set[str]):
    """Conservative source edges for Rust modules, not only include! macros.

    Top-level #[path] is relative to the physical source file. Inline modules
    and cfg_attr may change that directory; retain their consumer as opaque
    instead of guessing an active cfg or silently treating a module as prose.
    For ordinary outlined modules, consider both Rust directory conventions and
    root-module placement, retaining only paths in the exact Git tree. This is
    bounded discovery, not a replacement compiler or a proof of valid Rust.
    """
    targets = set()
    opaque = bool(INLINE_MODULE.search(text)) and bool(MODULE_PATH.search(text))
    opaque |= bool(re.search(r"#\s*\[\s*cfg_attr\b", text)) and bool(
        re.search(r"\bpath\s*=", text)
    )
    directory = posixpath.dirname(path)
    for attribute in MODULE_PATH.finditer(text):
        start = re.compile(r"\s*").match(text, attribute.end()).end()
        literal = INCLUDE_LITERAL.match(text, start)
        if literal is None or not re.match(r"\s*\]", text[literal.end() :]):
            opaque = True
            continue
        try:
            relative = (
                literal.group("raw")
                if literal.group("raw") is not None
                else json.loads('"' + literal.group("plain") + '"')
            )
        except (ValueError, TypeError):
            opaque = True
            continue
        if (
            not relative
            or "\\" in relative
            or posixpath.isabs(relative)
            or any(ord(char) < 32 for char in relative)
        ):
            opaque = True
            continue
        target = posixpath.normpath(posixpath.join(directory, relative))
        if target in {".", ".."} or target.startswith("../"):
            opaque = True
        elif target in tracked:
            targets.add(target)
        else:
            # A malformed/missing source must not acquire a prose-only pass.
            opaque = True
    stem = posixpath.splitext(posixpath.basename(path))[0]
    for module in OUTLINED_MODULE.finditer(text):
        name = module.group(1)
        for base in (directory, posixpath.join(directory, stem)):
            for suffix in (name + ".rs", name + "/mod.rs"):
                target = posixpath.normpath(posixpath.join(base, suffix))
                if target in tracked:
                    targets.add(target)
    return targets, opaque


def presentation_input(path: str) -> bool:
    return (
        path in PRESENTATION_INPUTS
        or (path.startswith("docs/") and path.endswith(".md"))
        or path.startswith("qualification/module-execution-dossiers/detail/")
        and path.endswith(".md")
    )


def cargo_source_inputs(manifests: dict[str, dict], owners: dict[str, str]):
    """Bind explicit Cargo source paths before classifying presentation inputs.

    Cargo targets and build scripts may live outside their package directory or
    use a non-.rs suffix. The manifest, not the filename, determines ownership.
    No target or build script is executed while discovering these dependencies.
    """
    inputs: set[tuple[str, str]] = set()

    def add(folder: str, relative: object) -> None:
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or any(ord(char) < 32 for char in relative)
            or posixpath.isabs(relative)
        ):
            raise ValueError("invalid Cargo source path")
        target = posixpath.normpath(posixpath.join(folder, relative))
        if target in {".", ".."} or target.startswith("../"):
            raise ValueError("Cargo source path leaves the exact repository")
        inputs.add((target, owners[folder]))

    for folder, document in manifests.items():
        library = document.get("lib", {})
        if not isinstance(library, dict):
            raise ValueError("invalid Cargo library declaration")
        targets = [library]
        for kind in ("bin", "example", "test", "bench"):
            declarations = document.get(kind, [])
            if not isinstance(declarations, list):
                raise ValueError(f"invalid Cargo {kind} declarations")
            targets.extend(declarations)
        for target in targets:
            if not isinstance(target, dict):
                raise ValueError("invalid Cargo target declaration")
            if "path" in target:
                add(folder, target["path"])
        build = document["package"].get("build")
        if isinstance(build, str):
            add(folder, build)
        elif build is not None and type(build) is not bool:
            raise ValueError("invalid Cargo build-script declaration")
    return frozenset(inputs)


def embedded_inputs(
    root: Path,
    revision: str,
    owners: dict[str, str],
    source_inputs: frozenset[tuple[str, str]] = frozenset(),
):
    """Read exact-tree includes without executing candidate build scripts.

    Literal includes give precise edges. Computed paths conservatively select
    their consumers for any input change. An include! target is Rust source
    regardless of its filename suffix and must be traversed recursively. Text
    and byte payloads are not parsed as Rust. Comments may over-select. Both old
    and new graphs retain removed edges. Cycles are bounded by (path, owner).
    """
    tracked = set(
        git(root, "ls-tree", "-r", "--name-only", "-z", revision)
        .decode("utf-8")
        .split("\0")
    )
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-C",
            str(root),
            "grep",
            "-l",
            "-z",
            "-E",
            r"include(_str|_bytes)?|mod[[:space:]]|#[[:space:]]*\[",
            revision,
            "--",
            "*.rs",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    # Explicit target paths are source entrypoints even when git grep's .rs
    # filter cannot find them or they are outside a conventional Cargo root.
    pending = list(source_inputs)
    prefix = revision + ":"
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        value = record.decode("utf-8")
        if not value.startswith(prefix):
            raise ValueError("unexpected exact-tree grep identity")
        path = value[len(prefix) :]
        folder = posixpath.dirname(path)
        while folder and folder not in owners:
            folder = posixpath.dirname(folder)
        if folder:
            pending.append((path, owners[folder]))

    @lru_cache(maxsize=None)
    def references(path: str):
        try:
            text = git(root, "show", f"{revision}:{path}").decode("utf-8")
        except (subprocess.CalledProcessError, UnicodeDecodeError):
            # A comment can mention a nonexistent fragment. Preserve unknown
            # input dependence instead of either breaking unrelated prose work
            # or silently deciding that this consumer has no dependencies.
            # Real missing/invalid source still fails its selected native build.
            return set(), set(), True
        targets, rust_sources, opaque = set(), set(), False
        for include in INCLUDE.finditer(text):
            start = re.compile(r"\s*").match(text, include.end()).end()
            literal = INCLUDE_LITERAL.match(text, start)
            if literal is None:
                opaque = True
                continue
            try:
                relative = (
                    literal.group("raw")
                    if literal.group("raw") is not None
                    else json.loads('"' + literal.group("plain") + '"')
                )
            except (ValueError, TypeError):
                opaque = True
                continue
            if "\\" in relative or "\0" in relative or posixpath.isabs(relative):
                opaque = True
                continue
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(path), relative)
            )
            if target == ".." or target.startswith("../"):
                opaque = True
            else:
                targets.add(target)
                if include.group("macro") == "include":
                    rust_sources.add(target)
        module_inputs, module_opaque = module_source_inputs(path, text, tracked)
        targets.update(module_inputs)
        rust_sources.update(module_inputs)
        return targets, rust_sources, opaque or module_opaque

    inputs, opaque, visited = set(source_inputs), set(), set()
    while pending:
        path, owner = pending.pop()
        if (path, owner) in visited:
            continue
        visited.add((path, owner))
        targets, rust_sources, unknown = references(path)
        if unknown:
            opaque.add(owner)
        inputs.update((target, owner) for target in targets)
        # Rust source fragments need not have a .rs suffix. Traverse include!
        # sources, never include_str!/include_bytes! payloads masquerading as code.
        pending.extend((target, owner) for target in rust_sources)
    return frozenset(inputs), frozenset(opaque)


def graph(root: Path, revision: str) -> Graph:
    if not OID.fullmatch(revision):
        raise ValueError("revision must be an exact Git SHA")
    paths = set(
        git(root, "ls-tree", "-r", "--name-only", "-z", revision)
        .decode("utf-8")
        .split("\0")
    )

    @lru_cache(maxsize=None)
    def load(path: str) -> dict:
        return tomllib.loads(git(root, "show", f"{revision}:{path}").decode("utf-8"))

    root_manifest = load(f"{WORKSPACE}/Cargo.toml")
    workspace = root_manifest["workspace"]
    available = {posixpath.dirname(p) for p in paths if p.endswith("/Cargo.toml")}
    excluded = [
        posixpath.normpath(f"{WORKSPACE}/{p}") for p in workspace.get("exclude", [])
    ]
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
                    targets = (
                        {posixpath.normpath(f"{dependency_root}/{declaration['path']}")}
                        if direct
                        else patch_paths.get(name, set())
                    )
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
                        if (
                            direct
                            and target.startswith(WORKSPACE + "/")
                            and not any(matches(target, e) for e in excluded)
                            and "workspace" not in target_doc
                        ):
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
    source_inputs = cargo_source_inputs(manifests, owners)
    inputs, opaque = embedded_inputs(root, revision, owners, source_inputs)
    # Build scripts are programs, not just include! declarations. They can read
    # an input under another Cargo owner's directory, even without an include
    # macro. Do not execute them or trust candidate-declared input lists while
    # planning. Until trusted dep-info can narrow the set, select these owners
    # (and their reverse consumers) for every nonempty exact-tree change set.
    # Cargo's automatic build.rs is disabled only by package.build = false.
    opaque |= frozenset(
        owners[folder]
        for folder, document in manifests.items()
        if document["package"].get("build") is not False
        and (
            document["package"].get("build") is not None
            or f"{folder}/build.rs" in paths
        )
    )
    return Graph(
        owners,
        edges,
        frozenset(owners[p] for p in members),
        conservative,
        inputs,
        opaque,
    )


def select_packages(paths: Iterable[str], before: Graph, after: Graph) -> dict:
    changed = set()
    reasons = set()
    has_changed_input = False
    input_owners: dict[str, set[str]] = {}
    for path, owner in before.external_inputs | after.external_inputs:
        input_owners.setdefault(path, set()).add(owner)
    # Resolve each revision independently: adding/removing a nested package
    # changes its parent's ownership even when the workspace manifest is unchanged.
    for path in paths:
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or ".." in parts
            or "\\" in path
            or "\0" in path
        ):
            raise ValueError(f"invalid repository path: {path!r}")
        has_changed_input = True
        if path in SHARED or path in {f"{WORKSPACE}/{p}" for p in SHARED}:
            reasons.add(f"shared build input: {path}")
            continue
        if path.startswith((".cargo/", f"{WORKSPACE}/.cargo/", ".github/", "scripts/")):
            reasons.add(f"shared CI input: {path}")
            continue
        consumers = input_owners.get(path, set())
        changed.update(consumers)
        if presentation_input(path):
            continue
        owned = bool(consumers)
        for mapping in (before.owners, after.owners):
            # Walking ancestors costs path depth, not a scan of every package
            # for every changed file. Only the deepest owner in each tree counts.
            folder = posixpath.dirname(path)
            while folder:
                if folder in mapping:
                    changed.add(mapping[folder])
                    owned = True
                    break
                folder = posixpath.dirname(folder)
        if not owned:
            reasons.add(f"unowned input: {path}")
            continue
        if path.endswith("/build.rs"):
            reasons.add(f"build script: {path}")
    # Opaque means the input path is unknown, not that its suffix must be .md.
    # A computed include may read another package's JSON, SQL or Rust fragment.
    # Union once after iterating paths to keep planning linear in changed paths
    # plus consumers, and leave an empty diff empty even for opaque readers.
    if has_changed_input:
        changed.update(before.opaque_input_consumers | after.opaque_input_consumers)
    current = after.targets
    if before.conservative or after.conservative:
        reasons.add("local registry override; full resolver fallback")
    if reasons:
        return {
            "packages": sorted(current),
            "full_workspace": True,
            "changed_packages": sorted(changed),
            "reasons": sorted(reasons),
        }
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
    return {
        "packages": sorted((affected | tests) & current),
        "full_workspace": False,
        "changed_packages": sorted(changed),
        "reasons": [],
    }


def plan(root: Path, base: str | None, tested: str) -> dict:
    after = graph(root, tested)
    if not base or not OID.fullmatch(base) or base == "0" * 40:
        return {
            "packages": sorted(after.targets),
            "full_workspace": True,
            "changed_packages": [],
            "reasons": ["no exact base"],
        }
    try:
        before = graph(root, base)
        paths = git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "--no-renames",
            "-z",
            base,
            tested,
            "--",
        )
    except (
        subprocess.CalledProcessError,
        ValueError,
        KeyError,
        tomllib.TOMLDecodeError,
    ):
        return {
            "packages": sorted(after.targets),
            "full_workspace": True,
            "changed_packages": [],
            "reasons": ["base graph unavailable; full fallback"],
        }
    return select_packages(
        (p.decode("utf-8") for p in paths.split(b"\0") if p), before, after
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--tested", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--run", action="store_true", help="execute the plan with just test --locked"
    )
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
