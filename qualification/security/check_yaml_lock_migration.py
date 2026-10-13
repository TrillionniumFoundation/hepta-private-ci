#!/usr/bin/env python3
"""Fail-closed scope audit for the maintained serde_yaml compatibility migration.

This only proves the dependency/lock migration, NOT full cargo-deny security.
Matrix SDK and any other inherited advisories stay explicitly unresolved.
Requires Python 3.11+ stdlib tomllib.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import tomllib

SHIM = "noyalib-serde-yaml"
CORE = "noyalib"
PIN = "0.0.56"
REMOVED = frozenset(("serde_yaml", "unsafe-libyaml"))
EXPECTED_DIRECT_USERS = frozenset((
    "codex-skills", "codex-skills-extension", "codex-core-plugins",
    "codex-external-agent-migration",
))
UNRESOLVED = (
    "RUSTSEC-2026-0318: matrix-sdk-crypto 0.18.0",
    "RUSTSEC-2026-0319: anymap2 0.13.0",
)


def read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def package_index(parsed: dict) -> dict[tuple, dict]:
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise ValueError("invalid Cargo.lock: missing package records")
    index: dict[tuple, dict] = {}
    for item in packages:
        key = (item["name"], item["version"], item.get("source", "workspace"))
        if key in index:
            raise ValueError(f"duplicate Cargo.lock package key {key!r}")
        index[key] = item
    return index


def check(before: dict, after: dict, manifest: dict) -> dict:
    deps = manifest.get("workspace", {}).get("dependencies", {})
    alias = deps.get("serde_yaml")
    if alias != {"package": SHIM, "version": f"={PIN}"}:
        raise ValueError("the workspace YAML alias is not the exact maintained shim")
    baseline = package_index(before)
    migrated = package_index(after)
    before_keys = set(baseline)
    after_keys = set(migrated)
    added = after_keys - before_keys
    removed = before_keys - after_keys
    names = Counter(key[0] for key in after_keys)
    if any(names.get(name, 0) for name in REMOVED):
        raise ValueError("archived serde_yaml/unsafe-libyaml package still in Cargo.lock")
    for name in (SHIM, CORE):
        match = [key for key in after_keys if key[0] == name]
        if len(match) != 1 or match[0][1] != PIN:
            raise ValueError(f"missing or incorrect exact pinned {name} = {PIN}")
        if match[0][2] != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"unexpected package origin for {name}")
    if any(key[0] == SHIM for key in before_keys):
        raise ValueError("baseline already migrated; audit must compare unmodified source")
    if any(key[0] not in REMOVED for key in removed):
        unexpected = sorted(key for key in removed if key[0] not in REMOVED)
        raise ValueError(f"unrelated baseline dependencies were removed: {unexpected[:10]}")
    changed = [
        key for key in sorted(before_keys & after_keys)
        if baseline[key] != migrated[key]
    ]
    # Cargo's resolver may select a *different already locked variant* of
    # transitive dependencies (e.g. windows-sys 0.59 -> already present 0.61).
    # Accept ONLY such version rebinding, never a new package/version, a new
    # dependency name, source/checksum change or a disappeared old version.
    # Record every such change for explicit human review.
    rebindings = []
    for key in changed:
        if key[0] in EXPECTED_DIRECT_USERS:
            continue
        old, new = baseline[key], migrated[key]
        old_rest = {k: v for k, v in old.items() if k != "dependencies"}
        new_rest = {k: v for k, v in new.items() if k != "dependencies"}
        if old_rest != new_rest:
            raise ValueError(f"unrelated immutable locked package metadata changed: {key}")
        old_deps = old.get("dependencies", [])
        new_deps = new.get("dependencies", [])
        if Counter(s.split(" ", 1)[0] for s in old_deps) != Counter(
            s.split(" ", 1)[0] for s in new_deps
        ):
            raise ValueError(f"unrelated locked dependency names/edges changed: {key}")
        before_by_name = {}
        after_by_name = {}
        for value in old_deps:
            before_by_name.setdefault(value.split(" ", 1)[0], []).append(value)
        for value in new_deps:
            after_by_name.setdefault(value.split(" ", 1)[0], []).append(value)
        for name in sorted(before_by_name):
            originals, replacements = sorted(before_by_name[name]), sorted(after_by_name[name])
            for old_dep, new_dep in zip(originals, replacements):
                if old_dep == new_dep:
                    continue
                if " " not in old_dep or " " not in new_dep:
                    raise ValueError(f"unqualified dependency identity changed: {key}")
                old_name, old_version = old_dep.split(" ", 1)
                new_name, new_version = new_dep.split(" ", 1)
                if old_name != new_name or not any(
                    entry[0] == new_name and entry[1] == new_version
                    for entry in before_keys & after_keys
                ):
                    raise ValueError(f"dependency rebind introduced an unreviewed version: {key}")
                rebindings.append({
                    "owner": key[0], "owner_version": key[1],
                    "dependency": name, "before": old_dep, "after": new_dep,
                })
    changed_direct = {key[0] for key in changed if key[0] in EXPECTED_DIRECT_USERS}
    if not changed_direct.issubset(EXPECTED_DIRECT_USERS):
        raise ValueError("unexpected first-party dependency change")
    for name in EXPECTED_DIRECT_USERS:
        found = [record for key, record in migrated.items() if key[0] == name]
        if len(found) != 1:
            raise ValueError(f"missing exact first-party direct user {name}")
        ds = found[0].get("dependencies", [])
        if SHIM not in ds or "serde_yaml" in ds:
            raise ValueError(f"{name} was not linked to maintained YAML shim")
    # These matrix advisories must stay visible: upgrading the YAML parser
    # is a deliberately independent, narrower qualification.
    return {
        "schema": "hepta.security.yaml-lock-replacement-audit.v1",
        "status": "yaml_lock_migration_verified_not_full_security_clearance",
        "yaml_parser": f"{SHIM}@{PIN}",
        "retired_dependency_names": sorted(REMOVED),
        "new_dependencies": sorted([list(key) for key in added]),
        "removed_dependencies": sorted([list(key) for key in removed]),
        "changed_direct_users": sorted(changed_direct),
        "preexisting_version_rebindings_for_review": rebindings,
        "other_dependency_records_changed": [],
        "advisory_ignore_added": False,
        "matrix_security_gate_passed": False,
        "global_cargo_deny_passed": False,
        "known_unresolved_advisories": list(UNRESOLVED),
        "production_promotion_permitted": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite preexisting audit evidence")
    report = check(
        read_toml(args.before),
        read_toml(args.after),
        read_toml(args.manifest),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
