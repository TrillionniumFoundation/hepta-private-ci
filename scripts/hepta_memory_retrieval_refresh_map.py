#!/usr/bin/env python3
"""Prepare a map-only source-observation commit without rewriting provenance.

Commit code first, run this at that exact clean HEAD, then commit only the map.
The qualification guard binds the resulting map-only head at execution time.
This command never changes a production, activation or release claim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

MAP = "docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json"
ROOT = "codex-rs/hepta-memory-retrieval"
INPUTS = (
    ROOT, "codex-rs/hepta-types", "codex-rs/hepta-cognitive-types",
    "codex-rs/hepta-cognitive-read", "codex-rs/hepta-cognitive-store",
    "codex-rs/hepta-memory", "codex-rs/hepta-agentd", "codex-rs/hepta-learning-ledger",
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
    "codex-rs/.cargo", ".cargo", "justfile",
    ".github/workflows/blocking-ci.yml",
    ".github/workflows/hepta-memory-retrieval-convergence.yml",
    ".github/workflows/hepta-memory-retrieval-qualification-host.yml",
    "scripts/hepta_memory_retrieval_qualification.py", "scripts/hepta_memory_retrieval_slo.py",
    # Conservative whole-workspace closure: transitive contract changes invalidate qualification.
    "codex-rs", "scripts", ".github/workflows", "MODULE.bazel", "MODULE.bazel.lock",
    "docs/modules/memory.retrieval", "qualification/memory-retrieval",
)


class RefreshError(ValueError):
    pass


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, timeout=60, check=False)
    if result.returncode:
        raise RefreshError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RefreshError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def refresh(root, head):
    root = Path(root)
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RefreshError("an exact lowercase source commit is required")
    if git(root, "rev-parse", "HEAD") != head:
        raise RefreshError("requested source is not the current checkout")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise RefreshError("commit all source changes before refreshing the map")
    mapping = json.loads((root / MAP).read_text(), object_pairs_hook=unique_object)
    if mapping.get("module") != "memory.retrieval":
        raise RefreshError("wrong module map")
    paths = sorted(set(INPUTS) | set(mapping.get("observedSourcePaths", [])))
    for path in paths:
        parts = Path(path).parts
        if not path or path.startswith(("/", ":")) or ".." in parts or "\\" in path or "\x00" in path:
            raise RefreshError("unsafe source input path")
    objects, missing = [], []
    for path in paths:
        # Do not bind the map or a tree containing the map to itself.
        if path == MAP or MAP.startswith(path.rstrip("/") + "/"):
            continue
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", f"{head}:{path}"],
                                capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            missing.append(path)
            continue
        identity = result.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", identity):
            raise RefreshError("unexpected Git object identity")
        objects.append({"path": path, "object": identity})
    if ROOT not in {row["path"] for row in objects}:
        raise RefreshError("retrieval source root is missing")
    mapping["observedAtHead"] = {"commit": head, "tree": git(root, "rev-parse", f"{head}^{{tree}}")}
    mapping["observedSourcePaths"] = paths
    mapping["sourceObjects"] = objects
    mapping["observedMissingPaths"] = missing
    # All ownership, operation mappings, sourceBase and claim fields are preserved.
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        mapping = refresh(args.root, args.head)
        path = args.root / MAP
        path.write_text(json.dumps(mapping, indent=2) + "\n")
        print(f"refreshed {MAP}; commit this file separately; no execution claim promoted")
    except (RefreshError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"memory.retrieval map refresh refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
