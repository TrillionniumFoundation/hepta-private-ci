#!/usr/bin/env python3
"""Select the smallest trustworthy CI boundary for an exact Git diff.

Known Hepta packages stay on the module-local path. Shared repository build
inputs and unknown non-Hepta code retain the full-repository fallback. Derived
views never acquire native scope merely because they are checked in.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
GROUPS = frozenset({"inference", "effects", "lifecycle", "learning", "objective"})


def generated_package_groups(root: Path = ROOT) -> dict[str, set[str]]:
    """Load package-to-risk ownership from the generated module manifest view.

    CI scope is not a second hand-maintained module registry.  New packages and
    changed risk groups become visible only through module.toml -> CI_MATRIX.
    A malformed or missing projection fails import rather than silently running
    too little CI.
    """
    path = root / "docs/modules/CI_MATRIX.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "hepta.module-ci-matrix.v1":
        raise ValueError(f"{path}: unsupported CI matrix schema")
    if set(document.get("groups", [])) != GROUPS:
        raise ValueError(f"{path}: CI group closure mismatch")
    result: dict[str, set[str]] = {}
    for row in document.get("packages", []):
        package_path = row.get("packagePath")
        groups = row.get("ciGroups")
        if (
            not isinstance(package_path, str)
            or not package_path.startswith("codex-rs/")
            or not isinstance(row.get("packageName"), str)
            or not row["packageName"].startswith("codex-hepta-")
            or not isinstance(groups, list)
            or any(group not in GROUPS for group in groups)
        ):
            raise ValueError(f"{path}: invalid package row")
        package_root = package_path.removeprefix("codex-rs/").rstrip("/")
        if not package_root or package_root in result:
            raise ValueError(f"{path}: duplicate or empty package root {package_root}")
        result[package_root] = set(groups)
    if not result:
        raise ValueError(f"{path}: empty package matrix")
    return result


PACKAGE_GROUPS = generated_package_groups()
MODULE_MANIFEST = re.compile(r"docs/modules/[a-z0-9_.-]+/module\.toml\Z")
MODULE_GROUPS: dict[str, set[str]] = {}
for _row in json.loads((ROOT / "docs/modules/CI_MATRIX.json").read_text())["packages"]:
    MODULE_GROUPS.setdefault(_row["module"], set()).update(_row["ciGroups"])


DERIVED_ONLY_DOCS = frozenset(
    {
        "docs/STATUS.md",
        "docs/learning/ALGORITHM_STATUS.md",
        "docs/readiness/STATUS.md",
        "docs/cns/STATUS.md",
        "docs/modules/SOURCE_BINDINGS.json",
        "docs/modules/MODULE_DOCS.json",
    }
)

FILE_GROUPS = {
    # Stable typed contracts with a single architecture concern should not
    # expand to every Hepta lane merely because they live in a shared crate.
    "codex-rs/hepta-types/src/topology.rs": {"lifecycle"},
    "codex-rs/hepta-control-plane/src/module_runtime.rs": {"lifecycle"},
    "codex-rs/hepta-control-plane/src/module_runtime_safety_tests.rs": {"lifecycle"},
    "codex-rs/hepta-supervisor/src/module_runtime.rs": {"lifecycle"},
    "codex-rs/hepta-supervisor/src/module_runtime_safety_tests.rs": {"lifecycle"},
    "codex-rs/hepta-fleet/src/module_catalog.rs": {"lifecycle"},
    "codex-rs/hepta-plasticity/src/topology_v3.rs": {"learning", "lifecycle"},
    "codex-rs/hepta-plasticity/src/durable_topology_registry.rs": {
        "learning",
        "lifecycle",
    },
}

CANONICAL_DOC_GROUPS = {
    "docs/modules/MODULES.json": {"lifecycle"},
    "docs/architecture/ARCHITECTURE.json": set(GROUPS),
    "docs/data/DATA_AUTHORITY.json": set(GROUPS),
    "CALLERS.toml": {"effects", "lifecycle"},
}


def select(paths: Iterable[str], *, force_full: bool = False) -> dict[str, bool]:
    selected = set(GROUPS) if force_full else set()
    derived = force_full
    full_repo = force_full
    native_desktop = force_full

    for path in paths:
        parts = PurePosixPath(path).parts
        if (
            not path
            or path.startswith("/")
            or ".." in parts
            or "\\" in path
            or "\x00" in path
        ):
            raise ValueError(f"invalid repository path: {path!r}")

        # This application has its own Cargo graph. A workspace-only test
        # cannot compile it, and an application-only edit needs no CLI rebuild.
        if path.startswith("apps/hepta-native/"):
            native_desktop = True
            continue
        if path.startswith(
            (
                "codex-rs/hepta-contracts/",
                "codex-rs/hepta-private-state/",
                "codex-rs/keyring-store/",
            )
        ):
            native_desktop = True

        if path in DERIVED_ONLY_DOCS or path.startswith(
            "qualification/module-execution-dossiers/detail/"
        ):
            derived = True
            continue

        if path in {"README.md", "CONTRIBUTING.md"} or (
            path.startswith("docs/") and path.endswith(".md")
        ):
            continue

        if MODULE_MANIFEST.fullmatch(path):
            # This is the canonical module input, not an unfamiliar TOML file.
            # Keep lifecycle validation and the module's owner lanes. Deleted
            # or newly introduced owners conservatively keep all Hepta lanes,
            # but never become a non-Hepta/full-repository change by suffix.
            selected.update(MODULE_GROUPS.get(parts[2], GROUPS))
            selected.add("lifecycle")
            derived = True
            continue

        if path in CANONICAL_DOC_GROUPS:
            selected.update(CANONICAL_DOC_GROUPS[path])
            derived = True
            continue

        if path.startswith("docs/contracts/") or path.startswith("docs/control-plane/"):
            selected.update(GROUPS)
            derived = True
            continue

        if path.startswith("docs/"):
            # Declarative documentation stays on the derived/static path.
            # Executable or unfamiliar file types under docs/ are not trusted
            # as prose merely because of their directory and retain the
            # conservative full-repository fallback.
            derived = True
            if PurePosixPath(path).suffix not in {".md", ".json", ".yaml", ".yml"}:
                selected.update(GROUPS)
                full_repo = True
            continue

        if path.startswith("apps/hepta-browser/"):
            selected.add("effects")
            continue

        if path in FILE_GROUPS:
            selected.update(FILE_GROUPS[path])
            continue

        if len(parts) > 2 and parts[0] == "codex-rs":
            relative = "/".join(parts[1:])
            matching_roots = [
                package_root
                for package_root in PACKAGE_GROUPS
                if relative == package_root or relative.startswith(package_root + "/")
            ]
            if matching_roots:
                package_root = max(matching_roots, key=len)
                selected.update(PACKAGE_GROUPS[package_root])
                continue
            if parts[1].startswith("hepta-") or (
                parts[1] == "ext" and len(parts) > 2 and parts[2].startswith("hepta-")
            ):
                # A newly introduced Hepta package stays inside architecture
                # qualification; workspace manifest/lock edits separately force
                # full repository validation.
                selected.update(GROUPS)
                continue
            full_repo = True
            selected.update(GROUPS)
            continue

        if path in {"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"}:
            full_repo = True
            selected.update(GROUPS)
            continue

        if path.startswith("scripts/hepta_ci_") or path.startswith(
            ".github/workflows/"
        ):
            full_repo = True
            selected.update(GROUPS)
            derived = True
            continue

        if path.startswith("scripts/hepta") or path.startswith("scripts/test_hepta"):
            derived = True
            continue

        # Unknown shared source/build inputs are the conservative escape hatch.
        full_repo = True
        selected.update(GROUPS)
        derived = True

    return {
        **{group: group in selected for group in sorted(GROUPS)},
        "native": bool(selected),
        "derived": derived,
        "full_repo": full_repo,
        "native_desktop": native_desktop or full_repo,
    }


def changed_paths(base: str, head: str) -> list[str]:
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
        raise ValueError(
            "base and head must be exact 40-character Git commit identities"
        )
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "--no-renames",
            "-z",
            base,
            head,
            "--",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [
        value.decode("utf-8", "strict") for value in result.stdout.split(b"\0") if value
    ]


def include_input_scope(
    scope: dict[str, bool],
    paths: list[str],
    base: str,
    head: str,
) -> dict[str, bool]:
    """Join embedded-input impact using exact Cargo OWNERS, never name guesses.

    Inspect all otherwise-static inputs, including JSON/YAML, not just prose.
    Only embedded inputs (or consumers with computed includes) widen native
    scope. Unrelated navigation documents remain lightweight. Native file-level
    scope is retained; this pass does not re-expand unrelated source changes.
    """
    if scope["full_repo"]:
        return scope
    static_paths = []
    for path in paths:
        boundary = select([path])
        if not boundary["native"] and not boundary["native_desktop"]:
            static_paths.append(path)
    if not static_paths:
        return scope
    try:
        from scripts.hepta_ci_dependencies import graph, select_packages
    except ModuleNotFoundError as error:
        if error.name != "scripts":
            raise
        from hepta_ci_dependencies import graph, select_packages
    import tomllib

    # An invalid candidate graph is a failure, never an empty test plan.
    after = graph(Path.cwd(), head)
    try:
        before = graph(Path.cwd(), base)
    except (
        subprocess.CalledProcessError,
        ValueError,
        KeyError,
        tomllib.TOMLDecodeError,
    ):
        return select([], force_full=True)
    embedded = {path for path, _ in before.external_inputs | after.external_inputs}
    affected = [path for path in static_paths if path in embedded]
    opaque = before.opaque_input_consumers | after.opaque_input_consumers
    # A computed include can consume any otherwise-static input. Seed its exact
    # old/new owner paths and retain the dependency planner's reverse/dev edges.
    affected.extend(
        f"{root}/Cargo.toml"
        for root, package in sorted(
            set(before.owners.items()) | set(after.owners.items())
        )
        if package in opaque
    )
    if not affected:
        return scope
    impact = select_packages(affected, before, after)
    if impact["full_workspace"]:
        return select([], force_full=True)
    packages = set(impact["packages"])
    roots = [
        f"{root}/Cargo.toml"
        for root, package in after.owners.items()
        if package in packages
    ]
    extra = select(roots)
    return {key: value or extra[key] for key, value in scope.items()}


def include_module_scope(
    scope: dict[str, bool],
    paths: list[str],
    base: str,
    head: str,
    *,
    root: Path = ROOT,
) -> dict[str, bool]:
    """Keep old owner lanes and semantic safety tests when manifests change.

    A high risk label alone does not run tests: workflow steps consume these
    booleans. Neither removing a CI group nor changing an authority field may
    omit its actual effect/recovery tests. Impact breadth remains independent.
    """
    manifests = [path for path in paths if MODULE_MANIFEST.fullmatch(path)]
    if not manifests:
        return scope
    try:
        from scripts.hepta_ci_modules import load_catalog, manifest_risk
    except ModuleNotFoundError as error:
        if error.name != "scripts":
            raise
        from hepta_ci_modules import load_catalog, manifest_risk
    import tomllib

    after = load_catalog(root, head)
    try:
        before = load_catalog(root, base)
    except (ValueError, subprocess.CalledProcessError, tomllib.TOMLDecodeError):
        return select([], force_full=True)
    result = dict(scope)
    for path in manifests:
        old, new = before.get(path), after.get(path)
        if old is None and new is None:
            raise ValueError(f"changed manifest absent from both exact trees: {path}")
        for row in (old, new):
            if row is None:
                continue
            for package in row.get("cargoPackages", []):
                groups = package.get("ciGroups", [])
                if not isinstance(groups, list) or any(
                    group not in GROUPS for group in groups
                ):
                    raise ValueError(f"invalid module CI groups: {path}")
                result.update({group: True for group in groups})
        risk = manifest_risk(old, new)
        if risk in {"stateful", "effect", "release"}:
            result["lifecycle"] = True
        if risk in {"effect", "release"}:
            result["effects"] = True
    result["native"] = any(result[group] for group in GROUPS)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", required=True)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.head):
        parser.error("--head must be an exact 40-character Git commit identity")
    if not args.full and not args.base:
        parser.error("an exact --base is required unless --full is explicitly selected")
    paths = [] if args.full else changed_paths(args.base, args.head)
    scope = select(paths, force_full=args.full)
    if not args.full:
        scope = include_input_scope(scope, paths, args.base, args.head)
        scope = include_module_scope(scope, paths, args.base, args.head)
    print(
        json.dumps(
            {
                "source_head": args.head,
                "base": args.base,
                "paths": paths,
                "scope": scope,
            },
            sort_keys=True,
        )
    )
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            for name, enabled in scope.items():
                stream.write(f"{name}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
