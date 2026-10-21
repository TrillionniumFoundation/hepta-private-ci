#!/usr/bin/env python3
"""Validate a disposable, pinned Hepta Matrix SDK adapter *compile candidate*.

This is a fail-closed preflight for a real Cargo invocation in isolated CI.
Metadata and SHA digests are diagnostics, NOT signed attestations or a
substitute for cargo-deny, E2EE, SQLite WAL/restart, or production promotion.
Never modifies the actual Cargo manifest, lockfile or deny.toml.
"""

import argparse
from collections import deque
import json
from pathlib import Path
import sys
import tomllib

from staged_resolution_probe import CANDIDATE_SPEC, SOURCE_SPEC, SQLITE_PATCH_SPEC
from upstream_source_probe import UPSTREAM_GIT_SHA

GIT_REMOTE = "https://github.com/matrix-org/matrix-rust-sdk"
REQUIRED_FEATURES = frozenset({"e2e-encryption", "sqlite"})
SDK_PACKAGES = ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite")
HEPTA_PACKAGES = ("codex-hepta-matrix-sdk", "codex-hepta-matrixd")
SCHEMA = "hepta.matrix-disposable-adapter-preflight.v1"


def _read_version(value):
    if not isinstance(value, str):
        raise ValueError("invalid component version")
    pieces = value.split(".")
    if len(pieces) != 3 or any(not part.isdecimal() for part in pieces):
        raise ValueError("invalid component version")
    return tuple(int(p) for p in pieces)


def _reaches(nodes, start, target):
    pending = deque([start])
    visited = set()
    while pending:
        node_id = pending.popleft()
        if node_id == target:
            return True
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes.get(node_id)
        if node is None:
            continue
        pending.extend(node.get("dependencies", []))
    return False


def audit(metadata, original_manifest, staged_manifest):
    errors = []
    try:
        original = tomllib.loads(original_manifest.decode("utf-8"))
        candidate = tomllib.loads(staged_manifest.decode("utf-8"))
        old_sdk = original["workspace"]["dependencies"]["matrix-sdk"]
        sdk = candidate["workspace"]["dependencies"]["matrix-sdk"]
        old_patch = original["patch"]["crates-io"]["matrix-sdk-sqlite"]
        new_patch = candidate.get("patch", {}).get("crates-io", {}).get("matrix-sdk-sqlite")
        if old_sdk != {
            "version": "0.18.0", "default-features": False,
            "features": ["e2e-encryption", "sqlite"]
        } or old_patch != {"path": "third_party/matrix-sdk-sqlite-0.18.0"}:
            errors.append("ORIGINAL_MATRIX_SECURITY_BASELINE_CHANGED")
        if sdk != {
            "git": GIT_REMOTE, "rev": UPSTREAM_GIT_SHA,
            "version": "0.19.1", "default-features": False,
            "features": ["e2e-encryption", "sqlite"]
        }:
            errors.append("UNPINNED_OR_WEAKENED_MATRIX_SDK")
        if new_patch is not None:
            errors.append("OBSOLETE_SQLITE_PATCH_STILL_PRESENT")
        if candidate.get("workspace", {}).get("dependencies", {}).get("matrix-sdk") == old_sdk:
            errors.append("MATRIX_SDK_NOT_STAGED")
    except (KeyError, TypeError, ValueError, UnicodeError, tomllib.TOMLDecodeError):
        errors.append("INVALID_OR_UNFROZEN_CARGO_MANIFEST")

    # The candidate may change ONLY the pinned SDK entry and the obsolete
    # SQLite override in a detached worktree. Reject any extra dependency,
    # feature, patch, toolchain, registry or workspace modification even if the
    # final metadata happens to appear advisory-free.
    try:
        original_text = original_manifest.decode("utf-8")
        expected = original_text.replace(SOURCE_SPEC, CANDIDATE_SPEC, 1)
        expected = expected.replace(SQLITE_PATCH_SPEC + "\n", "", 1)
        if (
            original_text.count(SOURCE_SPEC) != 1
            or original_text.count(SQLITE_PATCH_SPEC + "\n") != 1
            or expected.encode("utf-8") != staged_manifest
        ):
            errors.append("DISPOSABLE_WORKSPACE_MANIFEST_UNAUTHORIZED_DRIFT")
    except UnicodeError:
        errors.append("DISPOSABLE_WORKSPACE_MANIFEST_UNAUTHORIZED_DRIFT")

    packages = metadata.get("packages", []) if isinstance(metadata, dict) else []
    resolved = metadata.get("resolve") if isinstance(metadata, dict) else None
    if not isinstance(packages, list) or not isinstance(resolved, dict):
        errors.append("CARGO_METADATA_INCOMPLETE")
        packages = []
        resolved = {}
    by_name = {}
    for package in packages:
        if not isinstance(package, dict):
            errors.append("MALFORMED_CARGO_PACKAGE")
            continue
        name = package.get("name")
        package_id = package.get("id")
        if not isinstance(name, str) or not isinstance(package_id, str):
            errors.append("MALFORMED_CARGO_PACKAGE")
            continue
        by_name.setdefault(name, []).append(package)
    for name in (*SDK_PACKAGES, *HEPTA_PACKAGES, "anymap3"):
        if len(by_name.get(name, [])) != 1:
            errors.append("MISSING_OR_MULTIPLE_" + name.upper().replace("-", "_"))
    if by_name.get("anymap2"):
        errors.append("ANYMAP2_STILL_IN_GRAPH")
    versions = {}
    for name in SDK_PACKAGES:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            continue
        try:
            parsed = _read_version(matches[0].get("version"))
        except ValueError:
            errors.append("INVALID_" + name.upper().replace("-", "_") + "_VERSION")
            continue
        versions[name] = matches[0]["version"]
        if parsed[:2] != (0, 19):
            errors.append("SDK_FAMILY_MISMATCH_" + name.upper().replace("-", "_"))
    if versions.get("matrix-sdk") != "0.19.1":
        errors.append("CANDIDATE_SDK_IS_NOT_PINNED_0_19_1")
    crypto = versions.get("matrix-sdk-crypto")
    if crypto is not None and _read_version(crypto) < (0, 19, 0):
        errors.append("RUSTSEC_2026_0318_UNPATCHED")
    candidates = by_name.get("matrix-sdk", [])
    if len(candidates) == 1:
        source = candidates[0].get("source")
        if not isinstance(source, str) or not source.startswith("git+" + GIT_REMOTE) or (
            "rev=" + UPSTREAM_GIT_SHA not in source or not source.endswith("#" + UPSTREAM_GIT_SHA)
        ):
            errors.append("SDK_SOURCE_GIT_SHA_NOT_PINNED")

    nodes = {}
    for node in resolved.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            errors.append("INVALID_RESOLVED_NODE")
            continue
        if node["id"] in nodes:
            errors.append("DUPLICATE_RESOLVED_NODE")
        nodes[node["id"]] = node
    for name in (*HEPTA_PACKAGES, "matrix-sdk"):
        matches = by_name.get(name, [])
        if len(matches) == 1 and matches[0]["id"] not in nodes:
            errors.append("UNRESOLVED_" + name.upper().replace("-", "_"))
    if len(candidates) == 1:
        sdk_id = candidates[0]["id"]
        sdk_node = nodes.get(sdk_id, {})
        features = sdk_node.get("features", [])
        if not isinstance(features, list) or not REQUIRED_FEATURES.issubset(features):
            errors.append("SDK_E2EE_SQLITE_FEATURES_NOT_ENABLED")
        for required in ("matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite", "anymap3"):
            target = by_name.get(required, [])
            if len(target) != 1 or not _reaches(nodes, sdk_id, target[0]["id"]):
                errors.append("PINNED_SDK_NOT_LINKED_TO_" + required.upper().replace("-", "_"))
        for hepta_name in HEPTA_PACKAGES:
            hepta = by_name.get(hepta_name, [])
            if len(hepta) != 1 or not _reaches(nodes, hepta[0]["id"], sdk_id):
                errors.append("HEPTA_ADAPTER_NOT_LINKED_TO_PINNED_SDK_" + hepta_name.upper().replace("-", "_"))
    return {
        "schema": SCHEMA,
        "candidate_preflight_passed": not errors,
        "errors": sorted(set(errors)),
        "sdk_family_versions": versions,
        "matrix_rust_compiler": "1.96.0 (disposable only)",
        "production_source_modified": False,
        "hepta_adapter_compiled": False,
        "cargo_deny_verified": False,
        "e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--staged-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = [args.metadata.resolve(), args.source_manifest.resolve(), args.staged_manifest.resolve()]
    if args.output.resolve() in inputs:
        parser.error("candidate report may not overwrite any evidence inputs")
    data = json.loads(args.metadata.read_text(encoding="utf-8"))
    result = audit(data, args.source_manifest.read_bytes(), args.staged_manifest.read_bytes())
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["candidate_preflight_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
