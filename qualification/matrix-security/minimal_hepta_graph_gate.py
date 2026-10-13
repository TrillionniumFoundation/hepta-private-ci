#!/usr/bin/env python3
"""Strict graph preflight for the DISPOSABLE Hepta Matrix 0.19.1+AnyMap3 arm.

Accepting real Cargo metadata permits attempting a native compiler check; it
never passes cargo-deny, E2EE integration, SQLite WAL or production authorization.
"""

import argparse
import json
from pathlib import Path
import sys

SDK_FAMILY = ("matrix-sdk", "matrix-sdk-base", "matrix-sdk-crypto", "matrix-sdk-sqlite")
HEPTA_CALLERS = ("codex-hepta-matrix-sdk", "codex-hepta-matrixd")
SCHEMA = "hepta.matrix-minimal-hepta-graph.v1"


def reachable(nodes, start, destination):
    queue, visited = [start], set()
    while queue:
        item = queue.pop()
        if item == destination:
            return True
        if item in visited:
            continue
        visited.add(item)
        node = nodes.get(item)
        if node:
            queue.extend(node.get("dependencies", []))
    return False


def version_number(value):
    try:
        p = [int(x) for x in value.split(".")]
        if len(p) != 3 or any(x < 0 for x in p):
            raise ValueError
    except (AttributeError, ValueError):
        raise ValueError("malformed Matrix package version") from None
    return tuple(p)


def audit(metadata, sdk_root, hepta_root):
    sdk_root, hepta_root = Path(sdk_root).resolve(), Path(hepta_root).resolve()
    errors = []
    packages = metadata.get("packages") if type(metadata) is dict else None
    resolution = metadata.get("resolve") if type(metadata) is dict else None
    if type(packages) is not list or type(resolution) is not dict:
        packages, resolution = [], {}
        errors.append("INCOMPLETE_CARGO_METADATA")
    by_name = {}
    for item in packages:
        if type(item) is not dict or type(item.get("id")) is not str or type(item.get("name")) is not str:
            errors.append("MALFORMED_PACKAGE")
            continue
        by_name.setdefault(item["name"], []).append(item)
    if by_name.get("anymap2"):
        errors.append("RUSTSEC_2026_0319_ANYMAP2_STILL_PRESENT")
    if len(by_name.get("anymap3", [])) != 1:
        errors.append("MISSING_OR_DUPLICATE_MAINTAINED_ANYMAP3")
    # Guard the *whole* resolved Matrix family, not only four foreground
    # packages. An unnoticed 0.18 common/store-encryption crate would retain
    # transitive old crypto/SQLite assumptions despite a 0.19 SDK label.
    for name, versions in by_name.items():
        if not name.startswith("matrix-sdk-"):
            continue
        for item in versions:
            try:
                if version_number(item.get("version"))[:2] != (0, 19):
                    errors.append("MIXED_MATRIX_FAMILY_PACKAGE_" + name.upper().replace("-", "_"))
            except ValueError:
                errors.append("INVALID_MATRIX_FAMILY_PACKAGE_" + name.upper().replace("-", "_"))
    for name in (*SDK_FAMILY, *HEPTA_CALLERS):
        if len(by_name.get(name, [])) != 1:
            errors.append("MISSING_OR_DUPLICATE_" + name.upper().replace("-", "_"))
    components = {}
    for name in SDK_FAMILY:
        match = by_name.get(name, [])
        if len(match) != 1:
            continue
        p = match[0]
        components[name] = p.get("version")
        try:
            if version_number(p.get("version"))[:2] != (0, 19):
                errors.append("SDK_FAMILY_MISMATCH_" + name.upper().replace("-", "_"))
        except ValueError:
            errors.append("INVALID_VERSION_" + name.upper().replace("-", "_"))
        try:
            path = Path(p["manifest_path"]).resolve()
            if not path.is_relative_to(sdk_root / "crates") or p.get("source") is not None:
                errors.append("UNPINNED_UPSTREAM_SOURCE_" + name.upper().replace("-", "_"))
        except (KeyError, TypeError, ValueError):
            errors.append("UNPINNED_UPSTREAM_SOURCE_" + name.upper().replace("-", "_"))
    if components.get("matrix-sdk") != "0.19.1":
        errors.append("UNEXPECTED_SDK_RELEASE_VERSION")
    try:
        if version_number(components.get("matrix-sdk-crypto")) < (0, 19, 0):
            errors.append("RUSTSEC_2026_0318_CRYPTO_UNPATCHED")
    except ValueError:
        errors.append("MISSING_CRYPTO_VERSION")
    for name in HEPTA_CALLERS:
        match = by_name.get(name, [])
        if len(match) != 1:
            continue
        p = match[0]
        try:
            path = Path(p["manifest_path"]).resolve()
            if not path.is_relative_to(hepta_root / "codex-rs"):
                errors.append("UNPINNED_HEPTA_CALLER_" + name.upper().replace("-", "_"))
        except (KeyError, TypeError, ValueError):
            errors.append("UNPINNED_HEPTA_CALLER_" + name.upper().replace("-", "_"))
    nodes = {}
    for n in resolution.get("nodes", []):
        if type(n) is not dict or type(n.get("id")) is not str or type(n.get("dependencies")) is not list:
            errors.append("MALFORMED_RESOLVED_NODE")
            continue
        if n["id"] in nodes:
            errors.append("DUPLICATE_RESOLVED_NODE")
        nodes[n["id"]] = n
    sdk = by_name.get("matrix-sdk", [])
    if len(sdk) == 1:
        sdk_id = sdk[0]["id"]
        if sdk_id not in nodes:
            errors.append("UNRESOLVED_PINNED_SDK")
        if not {"e2e-encryption", "sqlite"}.issubset(set(nodes.get(sdk_id, {}).get("features", []))):
            errors.append("MATRIX_E2EE_OR_SQLITE_FEATURE_DISABLED")
        for name in (*SDK_FAMILY[1:], "anymap3"):
            target = by_name.get(name, [])
            if len(target) != 1 or not reachable(nodes, sdk_id, target[0]["id"]):
                errors.append("SDK_DISCONNECTED_FROM_" + name.upper().replace("-", "_"))
        for name in HEPTA_CALLERS:
            caller = by_name.get(name, [])
            if len(caller) != 1 or not reachable(nodes, caller[0]["id"], sdk_id):
                errors.append("HEPTA_NOT_LINKED_TO_PINNED_SDK_" + name.upper().replace("-", "_"))
    return {
        "schema": SCHEMA,
        "isolated_prerequisite_passed": not errors,
        "rejections": sorted(set(errors)),
        "sdk_family_versions": components,
        "sdk_source_root": str(sdk_root),
        "hepta_source_root": str(hepta_root),
        "cargo_metadata_parsed": type(metadata) is dict,
        "runtime_matrix_e2ee_verified": False,
        "sqlite_wal_crash_recovery_verified": False,
        "hepta_matrix_compiled": False,
        "cargo_deny_verified": False,
        "production_authorized": False,
    }


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--metadata", type=Path, required=True)
    cli.add_argument("--sdk-root", type=Path, required=True)
    cli.add_argument("--hepta-root", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args(argv)
    if args.output.exists() or any(
        args.output.resolve().is_relative_to(path.resolve())
        for path in (args.sdk_root, args.hepta_root)
    ):
        cli.error("report must be new and outside source roots")
    result = audit(json.loads(args.metadata.read_text(encoding="utf-8")),
                   args.sdk_root, args.hepta_root)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["isolated_prerequisite_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
