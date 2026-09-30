#!/usr/bin/env python3
"""Prepare a map-only source observation commit for an exact source snapshot.

Commit code and documentation first, run this at that exact clean HEAD, then
commit only the implementation map. The map binds the preceding source commit
through the repository-wide ``candidate_or_exact_observation_v1`` policy. This
command never changes a production, activation or release claim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

try:
    from scripts.hepta_memory_retrieval_policy import (
        INPUTS,
        MAP,
        OBJECT_INPUTS,
        PolicyError,
        ROOT,
        load_policy,
        safe_path,
    )
except ModuleNotFoundError:  # direct script execution from scripts/
    from hepta_memory_retrieval_policy import (  # type: ignore
        INPUTS,
        MAP,
        OBJECT_INPUTS,
        PolicyError,
        ROOT,
        load_policy,
        safe_path,
    )


SOURCE_IDENTITY_POLICY = "candidate_or_exact_observation_v1"


class RefreshError(ValueError):
    pass


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RefreshError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def remove_generated_python_caches(root: Path) -> None:
    """Remove import-only cache artifacts before enforcing a clean source tree."""
    scripts = root / "scripts"
    if not scripts.is_dir():
        return
    for cache in scripts.rglob("__pycache__"):
        relative = cache.relative_to(root).as_posix()
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if tracked.returncode == 0:
            raise RefreshError(f"refusing to remove tracked Python cache path: {relative}")
        shutil.rmtree(cache)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RefreshError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _git_object(root: Path, head: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{head}:{path}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        return None
    identity = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", identity):
        raise RefreshError("unexpected Git object identity")
    return identity


def _reject_map_self_reference(paths: tuple[str, ...]) -> None:
    for path in paths:
        if path == MAP or MAP.startswith(path.rstrip("/") + "/"):
            raise RefreshError(
                "sourceInputs must enumerate map-adjacent evidence without "
                f"including the implementation map or an ancestor of it: {path}"
            )


def refresh(root, head):
    root = Path(root)
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RefreshError("an exact lowercase source commit is required")
    if git(root, "rev-parse", "HEAD") != head:
        raise RefreshError("requested source is not the current checkout")
    remove_generated_python_caches(root)
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise RefreshError("commit all source changes before refreshing the map")

    try:
        policy = load_policy(root)
    except (OSError, ValueError, TypeError, KeyError, PolicyError) as error:
        raise RefreshError(f"qualification policy refused: {error}") from error
    canonical_inputs = tuple(policy["sourceInputs"])
    object_inputs = tuple(policy["sourceObjectInputs"])
    if canonical_inputs != INPUTS or object_inputs != OBJECT_INPUTS:
        raise RefreshError("loaded policy differs from the policy used by this process")
    _reject_map_self_reference(canonical_inputs)

    mapping = json.loads((root / MAP).read_text(), object_pairs_hook=unique_object)
    if mapping.get("module") != "memory.retrieval":
        raise RefreshError("wrong module map")

    inherited = mapping.get("observedSourcePaths", [])
    if not isinstance(inherited, list):
        raise RefreshError("observedSourcePaths must be a list")
    # Validate old values before discarding them so a poisoned inherited path can
    # never be normalized into an apparently clean map.
    for path in inherited:
        try:
            safe_path(path)
        except PolicyError as error:
            raise RefreshError(str(error)) from error

    source_identity = {
        "commit": head,
        "tree": git(root, "rev-parse", f"{head}^{{tree}}"),
    }
    objects, missing = [], []
    for path in canonical_inputs:
        if _git_object(root, head, path) is None:
            missing.append(path)

    for path in object_inputs:
        identity = _git_object(root, head, path)
        if identity is None:
            raise RefreshError(f"required source object is missing: {path}")
        objects.append({"path": path, "object": identity})

    if ROOT not in {row["path"] for row in objects}:
        raise RefreshError("retrieval source root is missing")
    mapping["sourceBase"] = dict(source_identity)
    mapping["observedAtHead"] = dict(source_identity)
    mapping["sourceIdentityPolicy"] = SOURCE_IDENTITY_POLICY
    mapping["observedSourcePaths"] = list(canonical_inputs)
    mapping["sourceObjects"] = objects
    mapping["observedMissingPaths"] = missing
    # Ownership, operations and all false claim fields are preserved.
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
        print(
            f"refreshed {MAP}; commit this file separately; "
            "no execution claim promoted"
        )
    except (
        RefreshError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"memory.retrieval map refresh refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
