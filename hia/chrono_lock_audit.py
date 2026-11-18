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
from pathlib import Path


def dependency_name(spec: str) -> str:
    """Cargo.lock may disambiguate package names with a version suffix."""
    return spec.split(" ", 1)[0]


def analyze_lock(data: bytes) -> dict:
    lock = tomllib.loads(data.decode("utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("Cargo.lock has no package array")

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
                "kind": "external" if entry.get("source") else "workspace",
            })

    imported.sort(key=lambda p: (p["kind"], p["name"], p["version"]))
    return {
        "schema": "codex.hia.chrono_dependency_audit.v1",
        "lock_git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "chrono_versions": sorted(installed),
        "importers": imported,
        "workspace_count": sum(x["kind"] == "workspace" for x in imported),
        "external_count": sum(x["kind"] == "external" for x in imported),
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
    parser.add_argument("--baseline", type=Path, help="optional pinned historical edge inventory")
    parser.add_argument("--fail-on-growth", action="store_true", help="fail on new chrono edges")
    parser.add_argument("--require-zero", action="store_true", help="fail until chrono is absent")
    args = parser.parse_args(argv)
    if args.fail_on_growth and not args.baseline:
        parser.error("--fail-on-growth requires --baseline")

    try:
        report = analyze_lock(args.lock.read_bytes())
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
