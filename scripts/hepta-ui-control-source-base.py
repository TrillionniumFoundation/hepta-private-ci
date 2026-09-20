#!/usr/bin/env python3
"""Verify ui.control's module-local source provenance without self-reference.

The tracked implementation map points at the last commit that changed the
module source root. Later map/docs/workflow-only commits may follow it, but any
change under apps/hepta-control-ui requires rebinding sourceBase.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/ui.control/IMPLEMENTATION_MAP.json"
SOURCE_ROOT = "apps/hepta-control-ui"
OID = re.compile(r"^[0-9a-f]{40}$")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        env.pop(key, None)
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(ROOT), *args],
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def fail(message: str) -> None:
    raise SystemExit(f"FAIL_HEPTA_UI_CONTROL_SOURCE_BASE: {message}")


def main() -> None:
    try:
        row = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"implementation map is unreadable: {exc}")

    if row.get("module") != "ui.control":
        fail("implementation map module identity mismatch")
    if row.get("declaredRoots") != [SOURCE_ROOT] or row.get("resolvedRoots") != [SOURCE_ROOT]:
        fail("ui.control source roots are not the exact registered root")

    source_base = row.get("sourceBase")
    if not isinstance(source_base, dict):
        fail("sourceBase must be an object")
    commit = source_base.get("commit")
    tree = source_base.get("tree")
    if not isinstance(commit, str) or not OID.fullmatch(commit):
        fail("sourceBase.commit must be a full lowercase commit OID")
    if not isinstance(tree, str) or not OID.fullmatch(tree):
        fail("sourceBase.tree must be a full lowercase tree OID")

    kind = git("cat-file", "-t", commit, check=False)
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        fail("sourceBase.commit is unavailable or not a commit")
    actual_tree = git("rev-parse", f"{commit}^{{tree}}").stdout.strip()
    if actual_tree != tree:
        fail("sourceBase.tree does not match sourceBase.commit")

    ancestor = git("merge-base", "--is-ancestor", commit, "HEAD", check=False)
    if ancestor.returncode != 0:
        fail("sourceBase.commit is not an ancestor of the candidate HEAD")

    drift = git("diff", "--quiet", commit, "HEAD", "--", SOURCE_ROOT, check=False)
    if drift.returncode == 1:
        fail("ui.control source changed after sourceBase; rebind the map")
    if drift.returncode != 0:
        fail("could not compare sourceBase with candidate HEAD")

    for args, label in (
        (("diff", "--quiet", "--", SOURCE_ROOT), "unstaged"),
        (("diff", "--cached", "--quiet", "--", SOURCE_ROOT), "staged"),
    ):
        dirty = git(*args, check=False)
        if dirty.returncode == 1:
            fail(f"ui.control has {label} tracked source changes")
        if dirty.returncode != 0:
            fail(f"could not inspect {label} ui.control source state")

    head = git("rev-parse", "HEAD").stdout.strip()
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_UI_CONTROL_SOURCE_BASE",
                "module": "ui.control",
                "sourceBase": {"commit": commit, "tree": tree},
                "candidateHead": head,
                "root": SOURCE_ROOT,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
