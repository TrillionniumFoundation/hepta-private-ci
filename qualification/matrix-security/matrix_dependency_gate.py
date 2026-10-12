#!/usr/bin/env python3
"""Fail-closed Matrix SDK upgrade prerequisite audit, without advisory waivers.

This is a static prerequisite for the *existing* cargo-deny / native E2EE and
SQLx/SQLite qualifications, never a replacement for them. It does not update
Cargo.toml, lockfiles, trust anchors, or publication permissions.
"""

import argparse
from collections import deque
import json
from pathlib import Path
import re
import sys
import tomllib

ADVISORY_CRYPTO = "RUSTSEC-2026-0318"
ADVISORY_ANYMAP = "RUSTSEC-2026-0319"
TARGET_REPLACEMENT = "anymap3"
# matrix-sdk 0.19.1 is the latest audited snapshot for this experiment. It
# requires Rust >=1.96 and STILL depends on anymap2; merely upgrading the SDK
# version is insufficient to pass cargo-deny.
UPSTREAM_019_MS_RUST = (1, 96)
ROOT = Path(__file__).resolve().parents[2]


def version(value):
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise ValueError(f"invalid fixed release version {value!r}")
    return tuple(int(n) for n in match.groups(default="0"))


def dependents(packages):
    """Map package names to normalized direct dependency names."""
    result = {}
    for p in packages:
        name, deps = p.get("name"), p.get("dependencies", [])
        if not isinstance(name, str) or not isinstance(deps, list):
            raise ValueError("malformed Cargo.lock package record")
        result.setdefault(name, set()).update(item.split()[0] for item in deps)
    return result


def find_path(graph, start, target):
    if start not in graph:
        return None
    frontier = deque([(start,)])
    visited = {start}
    while frontier:
        path = frontier.popleft()
        if path[-1] == target:
            return list(path)
        for child in sorted(graph.get(path[-1], ())):
            if child not in visited:
                visited.add(child)
                frontier.append((*path, child))
    return None


def _package_names(packages, name):
    return [p["version"] for p in packages if p.get("name") == name]


def _deny_ignore(deny):
    return {item if isinstance(item, str) else item.get("id")
            for item in deny.get("advisories", {}).get("ignore", [])}


def audit(workspace, lock, deny, toolchain, matrix_sdk_manifest, matrixd_manifest):
    errors = []
    notes = []
    graph = dependents(lock.get("package", []))
    pkgs = lock.get("package", [])
    sdk = workspace.get("workspace", {}).get("dependencies", {}).get("matrix-sdk")
    if not isinstance(sdk, dict):
        errors.append("MATRIX_SDK_WORKSPACE_PIN_MISSING")
        sdk = {}
    desired = sdk.get("version", "")
    if not isinstance(desired, str):
        desired = ""
    try:
        desired_tuple = version(desired)
    except ValueError:
        errors.append("MATRIX_SDK_VERSION_NOT_FIXED")
        desired_tuple = (0, 0, 0)
    features = set(sdk.get("features", [])) if isinstance(sdk.get("features", []), list) else set()
    if not {"e2e-encryption", "sqlite"}.issubset(features) or sdk.get("default-features") is not False:
        errors.append("REQUIRED_E2EE_SQLITE_FEATURES_REDUCED")
    if matrix_sdk_manifest.get("dependencies", {}).get("matrix-sdk", {}).get("workspace") is not True:
        errors.append("MATRIX_PRODUCTION_ADAPTER_UNPINNED")
    if matrixd_manifest.get("dev-dependencies", {}).get("matrix-sdk", {}).get("workspace") is not True:
        errors.append("MATRIX_E2EE_CONFORMANCE_DEPENDENCY_REMOVED")

    versions = {name: _package_names(pkgs, name) for name in
                ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto",
                 "matrix-sdk-sqlite", "anymap2", "anymap3")}
    if len(versions["matrix-sdk"]) != 1:
        errors.append("MATRIX_SDK_LOCK_AMBIGUOUS_OR_MISSING")
    elif version(versions["matrix-sdk"][0]) != desired_tuple:
        errors.append("MATRIX_SDK_WORKSPACE_LOCK_MISMATCH")

    if not versions["matrix-sdk-crypto"]:
        errors.append("MATRIX_CRYPTO_MISSING_WITH_E2EE_REQUIRED")
    elif any(version(v) < (0, 19, 0) for v in versions["matrix-sdk-crypto"]):
        errors.append(ADVISORY_CRYPTO)

    # A crypto-only bump is NOT a safe Matrix migration. A mixed 0.18/0.19
    # SDK/base/crypto/SQLite graph may look advisory-free while retaining an
    # unqualified state store and incompatible encrypted-session contracts.
    # Compare version families (major.minor), not patch releases: the upstream
    # SDK crates can ship different patch versions within a compatible family.
    for component in ("matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite"):
        observed = versions[component]
        if len(observed) != 1:
            errors.append(f"MATRIX_FAMILY_COMPONENT_MISSING_OR_AMBIGUOUS:{component}")
        elif desired_tuple != (0, 0, 0):
            try:
                if version(observed[0])[:2] != desired_tuple[:2]:
                    errors.append(f"MATRIX_FAMILY_RELEASE_MISMATCH:{component}")
            except ValueError:
                errors.append(f"MATRIX_FAMILY_INVALID_VERSION:{component}")
    # The selected production SDK must actually own its Base, SQLite and
    # Crypto dependencies. Unrelated safe-looking lockfile crates do not
    # repair a disconnected or pruned SDK feature graph.
    for component in ("matrix-sdk-base", "matrix-sdk-sqlite", "matrix-sdk-crypto"):
        if find_path(graph, "matrix-sdk", component) is None:
            errors.append(f"MATRIX_FAMILY_DEPENDENCY_PATH_MISSING:{component}")
    if versions["anymap2"] or "anymap2" in graph.get("matrix-sdk", ()):
        errors.append(ADVISORY_ANYMAP)
    if versions["matrix-sdk"] and desired_tuple >= (0, 19, 0):
        notes.append("0.19.x upgrade cannot remove anymap2 without an independently audited source migration")

    channel = toolchain.get("toolchain", {}).get("channel", "")
    try:
        rust_minor = version(channel)[:2]
    except ValueError:
        errors.append("RUST_TOOLCHAIN_NOT_FIXED")
        rust_minor = (0, 0)
    if desired_tuple >= (0, 19, 0) and rust_minor < UPSTREAM_019_MS_RUST:
        errors.append("MATRIX_019_RUST_MSRV_INCOMPATIBLE")

    patch = workspace.get("patch", {}).get("crates-io", {}).get("matrix-sdk-sqlite")
    if patch:
        patch_path = patch.get("path", "") if isinstance(patch, dict) else ""
        if not patch_path or not re.fullmatch(r"third_party/matrix-sdk-sqlite-\d+\.\d+\.\d+", patch_path):
            errors.append("MATRIX_SQLITE_PATCH_NOT_VERSIONED")
        elif desired_tuple[:2] != version(patch_path.rsplit("-", 1)[1])[:2]:
            errors.append("MATRIX_SQLITE_PATCH_RELEASE_MISMATCH")
    elif desired_tuple[:2] == (0, 18):
        errors.append("MATRIX_018_SQLITE_WAL_RESET_PATCH_MISSING")

    ignored = _deny_ignore(deny)
    for advisory in (ADVISORY_CRYPTO, ADVISORY_ANYMAP):
        if advisory in ignored:
            errors.append(f"FORBIDDEN_ADVISORY_IGNORE:{advisory}")
    # Deny's normal graph must remain full: no pruning to hide the vulnerable
    # Matrix dependency. This guard does not attempt to reinterpret cargo-deny.
    # Pruning Matrix's *consumer* removes its entire transitive E2EE graph:
    # looking only for the matrix-sdk package name misses a trivially renamed
    # selector like `codex-hepta-matrixd`. Storage/crypto dependencies must
    # likewise stay visible to unchanged cargo-deny.
    deny_graph = deny.get("graph", {})
    excluded = deny_graph.get("exclude", [])
    sensitive = ("matrix-sdk", "codex-hepta-matrixd", "anymap2",
                 "anymap3", "matrix-sdk-crypto", "sqlx", "rusqlite",
                 "libsqlite3-sys")
    if not isinstance(excluded, list) or any(
        any(name in str(item) for name in sensitive) for item in excluded
    ):
        errors.append("FORBIDDEN_MATRIX_GRAPH_PRUNE")
    # A single target triple can silently hide a platform-dependent SQLite or
    # encryption edge. Unchanged global cargo-deny must retain every target;
    # feature-filtered metadata also cannot certify the deployed E2EE graph.
    if deny_graph.get("targets"):
        errors.append("FORBIDDEN_MATRIX_TARGET_FILTER")
    if deny_graph.get("no-default-features") is True:
        errors.append("FORBIDDEN_MATRIX_DEFAULT_FEATURE_SUPPRESSION")

    for target in ("matrix-sdk", "matrix-sdk-crypto"):
        path = find_path(graph, "codex-hepta-matrixd", target)
        if path is None:
            errors.append(f"EXPECTED_MATRIX_DEPENDENCY_PATH_MISSING:{target}")
    if versions["anymap2"] and find_path(graph, "codex-hepta-matrixd", "anymap2") is None:
        errors.append("EXPECTED_MATRIX_DEPENDENCY_PATH_MISSING:anymap2")
    paths = {target: find_path(graph, "codex-hepta-matrixd", target)
             for target in ("matrix-sdk", "anymap2", "matrix-sdk-crypto")}
    # A *static* pass is never evidence for production approval; always run
    # cargo-deny, real Matrix E2EE, SQLite recovery and full target CI.
    return {
        "schema": "hepta.matrix-sdk-security-prerequisite.v1",
        "read_only": True,
        "matrix_sdk_requested_version": desired or None,
        "matrix_sdk_lock_versions": versions,
        "rust_toolchain": channel,
        "dependency_paths": paths,
        "blocking_prerequisites": sorted(set(errors)),
        "upstream_review_notes": notes,
        "static_prerequisites_passed": not errors,
        # An offline lockfile inspection cannot certify advisory remediation:
        # only unchanged cargo-deny plus real E2EE/recovery evidence can do so.
        "static_graph_advisory_candidates_clean": not errors and not versions["anymap2"],
        "security_advisories_resolved": False,
        "cargo_deny_verified": False,
        "matrix_e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def from_root(root):
    base = root / "codex-rs"
    values = []
    for path in (base / "Cargo.toml", base / "Cargo.lock", base / "deny.toml",
                 base / "rust-toolchain.toml", base / "hepta-matrix-sdk/Cargo.toml",
                 base / "hepta-matrixd/Cargo.toml"):
        values.append(tomllib.loads(path.read_text(encoding="utf-8")))
    return audit(*values)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Never-ignoring Matrix dependency-security gate")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-safe", action="store_true",
                        help="fail if unsafe; never replace cargo-deny or E2EE qualification")
    args = parser.parse_args(argv)
    result = from_root(args.root)
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
    if args.require_safe and not result["static_prerequisites_passed"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())