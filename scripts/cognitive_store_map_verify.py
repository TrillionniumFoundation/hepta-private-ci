#!/usr/bin/env python3
"""Read-only, exact-candidate verification of cognitive.store source bindings.

sourceBase is historical provenance. sourceObjects bind current source, callers,
delegates, tests and qualification inputs. Neither is an execution-success claim.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HOST = "codex-rs/hepta-agentd/src/production_writer_host.rs"
MANDATORY_INPUTS = (
    "scripts/cognitive_store_map_verify.py",
    "scripts/cognitive_store_map_generate.py",
    "scripts/test_cognitive_store_map.py",
    "scripts/verify_cognitive_store_boundary.py",
    "scripts/check-rust-module-inventory.py",
    "scripts/cognitive_qualification_manifest.py",
    ".github/workflows/cognitive-store-qualification.yml",
)
CLAIMS = (
    "productionImplementation", "productExecutionProved", "independentAcceptance",
    "activation", "release",
)


class Invalid(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=root, env=env, text=True, capture_output=True, check=True,
    ).stdout.strip()


def source_path(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("path", value.get("sourcePath"))
    require(isinstance(value, str) and bool(value), "missing mapped path")
    if ".rs::" in value:
        value = value.split(".rs::", 1)[0] + ".rs"
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value
            and all(part not in ("", ".", "..") for part in value.split("/"))
            and not any(char in value for char in ("\\", ":", "\x00", "\n", "\r")),
            "unsafe mapped path: " + repr(value))
    require(value != MAP_PATH, "the map cannot recursively bind its own Git object")
    return value


def mapped_paths(row: dict[str, Any]) -> set[str]:
    paths = set(MANDATORY_INPUTS)
    for key in ("resolvedRoots", "implementationRoots", "qualificationInputs"):
        values = row.get(key, [])
        require(isinstance(values, list), key + " must be a list")
        paths.update(source_path(value) for value in values)
    paths.add(source_path(row.get("technicalGuide")))
    for key in ("stateManifest", "statusDocument", "executionDossier"):
        if key in row:
            paths.add(source_path(row[key]))
    for key in ("productCallers", "readCallers"):
        for caller in row.get(key, []):
            paths.add(source_path(caller))
    operations = row.get("operations")
    require(isinstance(operations, list) and bool(operations), "operations are absent")
    names: set[str] = set()
    for operation in operations:
        require(isinstance(operation, dict), "malformed operation")
        name = operation.get("operation")
        require(isinstance(name, str) and bool(name) and name not in names,
                "missing or duplicate operation name")
        names.add(name)
        paths.add(source_path(operation.get("sourcePath")))
        for key in ("tests", "delegatedCallees"):
            paths.update(source_path(entry) for entry in operation.get(key, []))
    return paths


def object_at(root: Path, commit: str, path: str) -> str:
    path = source_path(path)
    entry = git(root, "ls-tree", commit, "--", path)
    require(bool(entry), "mapped path is absent from Git: " + path)
    header, actual_path = entry.split("\t", 1)
    mode, kind, oid = header.split()
    require(actual_path == path and mode in ("100644", "100755", "040000")
            and kind in ("blob", "tree") and HEX40.fullmatch(oid) is not None,
            "mapped object is not a regular file or tree: " + path)
    return oid


def validate_provenance(root: Path, value: Any, head: str, label: str) -> None:
    require(isinstance(value, dict), "missing " + label)
    commit, tree = value.get("commit"), value.get("tree")
    require(isinstance(commit, str) and HEX40.fullmatch(commit) is not None
            and isinstance(tree, str) and HEX40.fullmatch(tree) is not None,
            "invalid " + label)
    require(git(root, "rev-parse", f"{commit}^{{tree}}") == tree,
            label + " commit/tree mismatch")
    git(root, "merge-base", "--is-ancestor", commit, head)


def verify(root: Path, expected_sha: str, expected_tree: str) -> dict[str, Any]:
    head, tree = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")
    require(HEX40.fullmatch(expected_sha) is not None and expected_sha == head,
            "expected SHA mismatch")
    require(HEX40.fullmatch(expected_tree) is not None and expected_tree == tree,
            "expected tree mismatch")
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"),
            "candidate checkout is not clean")
    row = json.loads(git(root, "show", f"HEAD:{MAP_PATH}"))
    require(row.get("schema") == "hepta.module-implementation-map.v3"
            and row.get("module") == "cognitive.store", "wrong schema or module")
    validate_provenance(root, row.get("sourceBase"), head, "sourceBase")
    snapshot = row.get("sourceBindingSnapshot")
    if snapshot is not None:
        validate_provenance(root, snapshot, head, "sourceBindingSnapshot")
    paths = mapped_paths(row)
    objects = row.get("sourceObjects")
    require(isinstance(objects, list) and bool(objects), "sourceObjects are absent")
    observed: dict[str, str] = {}
    for entry in objects:
        require(isinstance(entry, dict), "malformed source object")
        path = source_path(entry.get("path"))
        require(path not in observed, "duplicate source object: " + path)
        current = object_at(root, head, path)
        require(entry.get("object") == current, "source object drift: " + path)
        if snapshot is not None:
            require(object_at(root, snapshot["commit"], path) == current,
                    "source differs from authored binding snapshot: " + path)
        observed[path] = current
    require(paths == set(observed),
            "source object inventory mismatch: missing=" + repr(sorted(paths - set(observed)))
            + " extra=" + repr(sorted(set(observed) - paths)))
    canonical = [{"sourcePath": HOST, "nativeSymbol": "AgentdProductionWriterHost",
                  "state": "canonical_production_write_facade"}]
    require(row.get("productCallers") == canonical, "canonical facade is not unique")
    hosts = [op for op in row["operations"] if op["operation"] == "product_writer_host"]
    require(len(hosts) == 1 and hosts[0].get("sourcePath") == HOST
            and hosts[0].get("nativeSymbol") == "AgentdProductionWriterHost",
            "operation map disagrees with the canonical facade")
    require(row.get("productionImplementation") is False, "unproved production claim")
    for name in CLAIMS:
        require(row.get("claimBoundary", {}).get(name) is False,
                "unproved claim is not false: " + name)
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"),
            "verification changed the source")
    return {"status": "PASS_COGNITIVE_STORE_MAP",
            "candidate": {"commit": head, "tree": tree}, "sourceBase": row["sourceBase"],
            "mappedPaths": len(paths), "sourceObjects": len(observed),
            "canonicalFacade": canonical[0], "executionClaim": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(ROOT, args.expected_sha, args.expected_tree), sort_keys=True))
    except (Invalid, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit("FAIL_COGNITIVE_STORE_MAP: " + str(error)) from error


if __name__ == "__main__":
    main()
