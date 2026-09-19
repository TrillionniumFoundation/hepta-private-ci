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
from pathlib import PurePosixPath
from typing import Iterable

GROUPS = frozenset({"inference", "effects", "lifecycle", "learning", "objective"})
PACKAGE_GROUPS = {
    "hepta-infer-core": {"inference"},
    "hepta-operations": {"effects", "lifecycle"},
    "hepta-automation": {"effects", "lifecycle"},
    "hepta-contracts": set(GROUPS),
    "hepta-control-plane": {"lifecycle", "effects", "objective"},
    "hepta-supervisor": {"lifecycle", "effects"},
    "hepta-fleet": {"lifecycle"},
    "hepta-agentd": set(GROUPS),
    "hepta-types": set(GROUPS),
    "hepta-learning-ledger": {"learning"},
    "hepta-learning-artifacts": {"learning"},
    "hepta-intelligence-eval": {"learning"},
    "hepta-objective": {"objective", "learning"},
    "hepta-prompt-optimizer": {"objective", "learning"},
    "hepta-plasticity": {"learning", "lifecycle"},
    "hepta-intelligence": {"objective", "learning"},
    "hepta-intuition": {"objective", "learning"},
    "hepta-neuron": {"learning"},
    "hepta-ndu": {"objective", "learning"},
    "hepta-cognitive-read": {"learning"},
    "hepta-cognitive-store": {"learning", "lifecycle"},
    "hepta-memory-retrieval": {"learning"},
    "hepta-memory-federation": {"learning", "lifecycle"},
    "hepta-prompt-registry": {"objective", "learning"},
}

DERIVED_ONLY_DOCS = frozenset({
    "docs/STATUS.md",
    "docs/learning/ALGORITHM_STATUS.md",
    "docs/readiness/STATUS.md",
    "docs/cns/STATUS.md",
    "docs/modules/SOURCE_BINDINGS.json",
    "docs/modules/MODULE_DOCS.json",
})

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

    for path in paths:
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or ".." in parts or "\\" in path or "\x00" in path:
            raise ValueError(f"invalid repository path: {path!r}")

        if path in DERIVED_ONLY_DOCS or path.startswith(
            "qualification/module-execution-dossiers/detail/"
        ):
            derived = True
            continue

        if path in {"README.md", "CONTRIBUTING.md"} or (
            path.startswith("docs/") and path.endswith(".md")
        ):
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

        if len(parts) > 2 and parts[0] == "codex-rs":
            package = parts[1]
            if package in PACKAGE_GROUPS:
                selected.update(PACKAGE_GROUPS[package])
                continue
            if package.startswith("hepta-"):
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

        if path.startswith("scripts/hepta_ci_") or path.startswith(".github/workflows/"):
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
    }


def changed_paths(base: str, head: str) -> list[str]:
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
        raise ValueError("base and head must be exact 40-character Git commit identities")
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
    return [value.decode("utf-8", "strict") for value in result.stdout.split(b"\0") if value]


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
    print(json.dumps({"source_head": args.head, "base": args.base, "paths": paths, "scope": scope}, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            for name, enabled in scope.items():
                stream.write(f"{name}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
