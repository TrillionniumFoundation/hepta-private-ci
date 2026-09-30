#!/usr/bin/env python3
"""Seal one exact memory.retrieval candidate without mutating source in CI.

The candidate protocol has two Git objects:

1. an exact source commit containing code, policy, workflow and documentation;
2. its direct child changing only ``IMPLEMENTATION_MAP.json``.

At a source commit this command emits a proposed map and candidate identity. At
an exact map-only child it verifies the map against the parent and emits a
sealed identity. The default output remains the tracked map for developer use;
CI passes explicit output paths outside the checkout. No execution, production,
activation or release claim is promoted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
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
SEAL_SCHEMA = "hepta.memory-retrieval.candidate-seal.v1"


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


def git_stdin(root: Path, value: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=value,
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


def _validate_checkout(root: Path, head: str) -> None:
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RefreshError("an exact lowercase candidate commit is required")
    if git(root, "rev-parse", "HEAD") != head:
        raise RefreshError("requested candidate is not the current checkout")
    remove_generated_python_caches(root)
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise RefreshError("commit all source changes before refreshing the map")


def _load_mapping(root: Path) -> dict:
    mapping = json.loads((root / MAP).read_text(), object_pairs_hook=unique_object)
    if mapping.get("module") != "memory.retrieval":
        raise RefreshError("wrong module map")
    inherited = mapping.get("observedSourcePaths", [])
    if not isinstance(inherited, list):
        raise RefreshError("observedSourcePaths must be a list")
    for path in inherited:
        try:
            safe_path(path)
        except PolicyError as error:
            raise RefreshError(str(error)) from error
    return mapping


def _load_inputs(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        policy = load_policy(root)
    except (OSError, ValueError, TypeError, KeyError, PolicyError) as error:
        raise RefreshError(f"qualification policy refused: {error}") from error
    canonical_inputs = tuple(policy["sourceInputs"])
    object_inputs = tuple(policy["sourceObjectInputs"])
    if canonical_inputs != INPUTS or object_inputs != OBJECT_INPUTS:
        raise RefreshError("loaded policy differs from the policy used by this process")
    _reject_map_self_reference(canonical_inputs)
    return canonical_inputs, object_inputs


def _build_mapping(root: Path, source_head: str, inherited: dict) -> dict:
    canonical_inputs, object_inputs = _load_inputs(root)
    mapping = copy.deepcopy(inherited)
    source_identity = {
        "commit": source_head,
        "tree": git(root, "rev-parse", f"{source_head}^{{tree}}"),
    }
    objects, missing = [], []
    for path in canonical_inputs:
        if _git_object(root, source_head, path) is None:
            missing.append(path)

    for path in object_inputs:
        identity = _git_object(root, source_head, path)
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
    # Ownership, operations and every fail-closed claim are preserved.
    return mapping


def refresh(root, head):
    """Generate a proposed map for the exact checked-out source commit."""
    root = Path(root)
    _validate_checkout(root, head)
    return _build_mapping(root, head, _load_mapping(root))


def _single_parent(root: Path, head: str) -> str | None:
    parents = git(root, "show", "-s", "--format=%P", head).split()
    return parents[0] if len(parents) == 1 else None


def _changed_paths(root: Path, base: str, head: str) -> tuple[str, ...]:
    output = git(root, "diff", "--name-only", base, head)
    return tuple(line for line in output.splitlines() if line)


def _serialize(mapping: dict) -> str:
    return json.dumps(mapping, indent=2) + "\n"


def _map_blob(root: Path, serialized: str) -> str:
    identity = git_stdin(root, serialized, "hash-object", "--stdin")
    if not re.fullmatch(r"[0-9a-f]{40}", identity):
        raise RefreshError("unexpected proposed map object identity")
    return identity


def _seal(
    root: Path,
    state: str,
    source_head: str,
    mapping: dict,
    serialized: str,
    candidate_head: str | None,
) -> dict:
    candidate_tree = (
        git(root, "rev-parse", f"{candidate_head}^{{tree}}")
        if candidate_head is not None
        else None
    )
    actual_blob = (
        _git_object(root, candidate_head, MAP)
        if candidate_head is not None
        else None
    )
    proposed_blob = _map_blob(root, serialized)
    if actual_blob is not None and actual_blob != proposed_blob:
        raise RefreshError("sealed candidate map blob differs from canonical serialization")
    claim_boundary = mapping.get("claimBoundary", {})
    if not isinstance(claim_boundary, dict):
        raise RefreshError("claimBoundary must be an object")
    return {
        "schema": SEAL_SCHEMA,
        "module": "memory.retrieval",
        "state": state,
        "source_head_sha": source_head,
        "source_tree_sha": mapping["sourceBase"]["tree"],
        "candidate_head_sha": candidate_head,
        "candidate_tree_sha": candidate_tree,
        "implementation_map_path": MAP,
        "implementation_map_blob_sha": proposed_blob,
        "implementation_map_sha256": hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest(),
        "source_identity_policy": SOURCE_IDENTITY_POLICY,
        "claim_boundary": claim_boundary,
        "repository_checks_satisfied": False,
        "implementation_ready": False,
        "production_ready": False,
        "merge_ready": False,
    }


def stage(root, head):
    """Return the canonical map and a proposal/sealed identity for current HEAD."""
    root = Path(root)
    _validate_checkout(root, head)
    inherited = _load_mapping(root)
    parent = _single_parent(root, head)
    if parent is not None and _changed_paths(root, parent, head) == (MAP,):
        expected = _build_mapping(root, parent, inherited)
        serialized = _serialize(inherited)
        if inherited != expected or serialized != _serialize(expected):
            raise RefreshError(
                "map-only candidate does not exactly bind its source parent"
            )
        return inherited, _seal(
            root,
            "sealed",
            parent,
            inherited,
            serialized,
            head,
        )

    mapping = _build_mapping(root, head, inherited)
    serialized = _serialize(mapping)
    return mapping, _seal(root, "proposal", head, mapping, serialized, None)


def _projection(seal: dict) -> str:
    candidate = seal["candidate_head_sha"] or "not-created"
    candidate_tree = seal["candidate_tree_sha"] or "not-created"
    return "\n".join(
        [
            "## Authoritative candidate identity",
            "",
            f"- state: `{seal['state']}`",
            f"- frozen implementation-source commit: `{seal['source_head_sha']}`",
            f"- frozen implementation-source tree: `{seal['source_tree_sha']}`",
            f"- exact map-only observation head: `{candidate}`",
            f"- map-only tree: `{candidate_tree}`",
            f"- implementation-map blob: `{seal['implementation_map_blob_sha']}`",
            f"- implementation-map sha256: `{seal['implementation_map_sha256']}`",
            "",
            "Generated facts:",
            "",
            "- `repository_checks_satisfied = false`",
            "- `implementation_ready = false`",
            "- `production_ready = false`",
            "- `merge_ready = false`",
            "",
            "The map-only observation must be the direct child of the frozen source "
            "and change only `docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json`. "
            "Workflow results from any other SHA or attempt are ineligible.",
            "",
        ]
    )


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help=f"map output; defaults to the tracked {MAP}",
    )
    parser.add_argument("--identity-output", type=Path)
    parser.add_argument("--projection-output", type=Path)
    args = parser.parse_args()
    try:
        mapping, seal = stage(args.root, args.head)
        serialized = _serialize(mapping)
        output = args.output or (args.root / MAP)
        _write(output, serialized)
        if args.identity_output is not None:
            _write(args.identity_output, json.dumps(seal, indent=2) + "\n")
        if args.projection_output is not None:
            _write(args.projection_output, _projection(seal))
        print(
            f"{seal['state']} memory.retrieval candidate: "
            f"source={seal['source_head_sha']} "
            f"candidate={seal['candidate_head_sha'] or 'pending'} "
            f"map={seal['implementation_map_blob_sha']}; "
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
