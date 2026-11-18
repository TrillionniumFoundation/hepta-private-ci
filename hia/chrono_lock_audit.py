#!/usr/bin/env python3
"""Identify all chrono dependency edges in a pinned Cargo.lock without running Cargo.

This deliberately does not suppress RustSec advisories, modify dependencies or
claim that a successful source scan is a build, platform or security qualification.
"""

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path, PurePosixPath


def dependency_name(spec: str) -> str:
    """Cargo.lock may disambiguate package names with a version suffix."""
    return spec.split(" ", 1)[0]


def vendored_patch_names(workspace_data: bytes) -> set[str]:
    manifest = tomllib.loads(workspace_data.decode("utf-8"))
    root = manifest.get("patch", {})
    if not isinstance(root, dict):
        raise ValueError("workspace patch must be a table")
    patch = root.get("crates-io", {})
    if not isinstance(patch, dict):
        raise ValueError("workspace patch.crates-io must be a table")
    names = set()
    for name, item in patch.items():
        if not isinstance(item, dict):
            raise ValueError(f"invalid patch entry {name}")
        path = item.get("path")
        if path is not None and not isinstance(path, str):
            raise ValueError(f"invalid patch path {name}")
        if path and PurePosixPath(path).parts[:1] == ("third_party",):
            names.add(name)
    return names


def analyze_lock(data: bytes, workspace_data: bytes = b"") -> dict:
    lock = tomllib.loads(data.decode("utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("Cargo.lock has no package array")

    vendored = vendored_patch_names(workspace_data)
    imported = []
    installed = []
    for entry in packages:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("malformed Cargo.lock package entry")
        if entry["name"] == "chrono":
            installed.append(entry.get("version", "unknown"))
        dependencies = entry.get("dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise ValueError("malformed Cargo.lock dependency array")
        if any(dependency_name(x) == "chrono" for x in dependencies):
            imported.append({
                "name": entry["name"],
                "version": entry.get("version", "unknown"),
                "kind": "vendored_external" if entry["name"] in vendored and not entry.get("source")
                        else "registry_external" if entry.get("source") else "workspace_local",
            })

    imported.sort(key=lambda p: (p["kind"], p["name"], p["version"]))
    return {
        "schema": "codex.hia.chrono_dependency_audit.v2",
        "workspace_manifest_git_blob": hashlib.sha1(b"blob " + str(len(workspace_data)).encode() + b"\0" + workspace_data).hexdigest(),
        "lock_git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "chrono_versions": sorted(installed),
        "importers": imported,
        "workspace_local_count": sum(x["kind"] == "workspace_local" for x in imported),
        "registry_external_count": sum(x["kind"] == "registry_external" for x in imported),
        "vendored_external_count": sum(x["kind"] == "vendored_external" for x in imported),
        "closure_ready": not installed and not imported,
    }


def importer_key(entry: dict) -> tuple[str, str, str]:
    return entry["kind"], entry["name"], entry["version"]


def comparison(report: dict, baseline: dict) -> dict:
    if baseline.get("schema") != report["schema"]:
        raise ValueError("baseline schema mismatch")
    current = {importer_key(p) for p in report["importers"]}
    before = {importer_key(p) for p in baseline["importers"]}
    return {
        "new_edges": [list(p) for p in sorted(current - before)],
        "retired_edges": [list(p) for p in sorted(before - current)],
        "remaining_edges": len(current),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path, help="exact Cargo.lock to inspect")
    parser.add_argument("--workspace-manifest", type=Path, help="default: Cargo.toml alongside Cargo.lock")
    parser.add_argument("--baseline", type=Path, help="optional pinned historical edge inventory")
    parser.add_argument("--fail-on-growth", action="store_true", help="fail on new chrono edges")
    parser.add_argument("--require-zero", action="store_true", help="fail until chrono is absent")
    args = parser.parse_args(argv)
    if args.fail_on_growth and not args.baseline:
        parser.error("--fail-on-growth requires --baseline")

    try:
        workspace_manifest = args.workspace_manifest or args.lock.with_name("Cargo.toml")
        report = analyze_lock(args.lock.read_bytes(), workspace_manifest.read_bytes())
        if args.baseline:
            report["compared_to"] = str(args.baseline)
            report["delta"] = comparison(report, json.loads(args.baseline.read_text()))
    except (ValueError, UnicodeError, KeyError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"chrono dependency audit: {error}", file=sys.stderr)
        return 1

    print(json.dumps(report, sort_keys=True, indent=2))
    if args.require_zero and not report["closure_ready"]:
        return 2
    if args.fail_on_growth and report["delta"]["new_edges"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
