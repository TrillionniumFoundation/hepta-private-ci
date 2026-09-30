#!/usr/bin/env python3
"""Verify the exact-blob implementation map for cognitive.read only."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"
HEX_SHA = re.compile(r"[0-9a-f]{40}")


def git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    process = subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return process.stdout.strip()


def identity(value: object, label: str, candidate: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a commit/tree object")
    commit = value.get("commit")
    tree = value.get("tree")
    if not isinstance(commit, str) or HEX_SHA.fullmatch(commit) is None:
        raise SystemExit(f"{label}.commit must be a complete SHA")
    if not isinstance(tree, str) or HEX_SHA.fullmatch(tree) is None:
        raise SystemExit(f"{label}.tree must be a complete SHA")
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise SystemExit(f"{label} tree does not match its commit")
    try:
        git("merge-base", "--is-ancestor", commit, candidate)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"{label} commit is not an ancestor of the candidate") from error
    return {"commit": commit, "tree": tree}


def source_objects(mapping: dict[str, object], candidate: str) -> dict[str, str]:
    entries = mapping.get("sourceObjects")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("sourceObjects must be a non-empty list")
    objects: dict[str, str] = {}
    root = ROOT.resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("sourceObjects entries must be objects")
        path = entry.get("path")
        blob = entry.get("object")
        if not isinstance(path, str) or not path:
            raise SystemExit("sourceObjects entry is missing path")
        if not isinstance(blob, str) or HEX_SHA.fullmatch(blob) is None:
            raise SystemExit(f"sourceObjects has invalid object for {path}")
        if path in objects:
            raise SystemExit(f"duplicate sourceObjects path: {path}")
        local = (ROOT / path).resolve()
        if not local.is_relative_to(root) or not local.exists():
            raise SystemExit(f"missing or escaping sourceObjects path: {path}")
        actual = git("rev-parse", f"{candidate}:{path}")
        if actual != blob:
            raise SystemExit(f"source object drift: {path}")
        objects[path] = blob
    return objects


def verify_exact_manifest(mapping: dict[str, object], objects: dict[str, str]) -> None:
    evidence = mapping.get("exactSourceEvidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict) or evidence.get("kind") != "path_blob_manifest_v1":
        raise SystemExit("exactSourceEvidence must use path_blob_manifest_v1 when present")
    entries = evidence.get("entries")
    if not isinstance(entries, list):
        raise SystemExit("exactSourceEvidence.entries must be a list")
    manifest: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("exact source manifest entries must be objects")
        path = entry.get("path")
        blob = entry.get("blobSha")
        if not isinstance(path, str) or not isinstance(blob, str):
            raise SystemExit("invalid exact source manifest entry")
        if path in manifest:
            raise SystemExit(f"duplicate exact source manifest path: {path}")
        manifest[path] = blob
    extra = sorted(set(manifest).difference(objects))
    drifted = sorted(
        path for path in set(objects).intersection(manifest) if objects[path] != manifest[path]
    )
    if extra or drifted:
        raise SystemExit(
            "exact source manifest disagrees with sourceObjects: "
            f"extra={extra}, drifted={drifted}"
        )


def collect_activation(value: object) -> list[object]:
    found: list[object] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "activation":
                found.append(child)
            found.extend(collect_activation(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_activation(child))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree")
    args = parser.parse_args()

    expected_sha = args.expected_sha.lower()
    if HEX_SHA.fullmatch(expected_sha) is None:
        raise SystemExit("--expected-sha must be a complete lowercase SHA")
    actual_sha = git("rev-parse", "HEAD")
    if actual_sha != expected_sha:
        raise SystemExit(f"candidate mismatch: expected {expected_sha}, got {actual_sha}")
    actual_tree = git("rev-parse", "HEAD^{tree}")
    if args.expected_tree is not None and actual_tree != args.expected_tree.lower():
        raise SystemExit(
            f"candidate tree mismatch: expected {args.expected_tree.lower()}, got {actual_tree}"
        )
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("tracked candidate worktree is not clean")

    try:
        mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid cognitive.read implementation map: {error}") from error
    if mapping.get("module") != "cognitive.read":
        raise SystemExit("implementation map has the wrong module identity")
    mapping_mode = mapping.get("mappingSourceIdentityMode", "path_only")
    if mapping_mode not in {"path_only", "exact_blob"}:
        raise SystemExit(f"unsupported mapping source identity mode: {mapping_mode}")
    if mapping.get("sourceIdentityPolicy") != "candidate_or_exact_observation_v1":
        raise SystemExit("cognitive.read has the wrong source identity policy")
    activations = collect_activation(mapping)
    if not activations or any(value is not False for value in activations):
        raise SystemExit("activation must remain explicitly false")

    identity(mapping.get("sourceBase"), "sourceBase", expected_sha)
    observed = identity(mapping.get("observedAtHead"), "observedAtHead", expected_sha)
    objects = source_objects(mapping, expected_sha)
    verify_exact_manifest(mapping, objects)

    changed = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        observed["commit"],
        expected_sha,
        "--",
        *sorted(objects),
    )
    if changed:
        raise SystemExit(f"mapped source changed after observedAtHead:\n{changed}")

    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_READ_IMPLEMENTATION_MAP",
                "candidate": {"commit": expected_sha, "tree": actual_tree},
                "observedAtHead": observed,
                "sourceObjects": len(objects),
                "activation": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
