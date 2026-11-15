#!/usr/bin/env python3
"""Fail closed on inconsistent Codex/HIA migration and source-retirement claims.

This is a declaration-consistency gate, not executed behavioral or platform proof.
"""
import argparse
import json
from pathlib import Path

CAPABILITIES = frozenset({
    "model_transport", "authentication_identity", "thread_turn_execution",
    "history_storage_recovery", "tools_processes_files", "permissions_sandbox",
    "mcp", "app_server_v2", "cli_tui", "sdk_frontends",
    "patch_application", "string_utilities", "hepta_cells_and_adapters",
    "platforms_build_release", "hia_toolchain",
})
COMPLETE = frozenset({"qualified", "complete", "fully_qualified"})


def validate(migration: dict, verification: dict) -> list[str]:
    """Return every violated invariant; do not modify either input."""
    errors: list[str] = []
    if migration.get("schema") != "codex.hia.migration.v1":
        errors.append("unexpected migration schema")
    if verification.get("schema") != "codex.hia.component-verification.v2":
        errors.append("unexpected verification schema")
    capabilities = migration.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
        errors.append("capabilities must be a list")
    ids = [c.get("id") for c in capabilities if isinstance(c, dict)]
    if (len(ids) != len(capabilities) or
            any(not isinstance(x, str) or not x for x in ids) or
            len(ids) != len(set(x for x in ids if isinstance(x, str)))):
        errors.append("duplicate or invalid capability entries")
    missing = sorted(CAPABILITIES - {x for x in ids if isinstance(x, str)})
    if missing:
        errors.append("missing original capability groups: " + ", ".join(missing))
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        if type(item.get("production_dispatch_migrated")) is not bool:
            errors.append(f"{item.get('id')}: dispatch flag must be boolean")
        if not isinstance(item.get("migration_status"), str):
            errors.append(f"{item.get('id')}: status must be a string")

    modules = migration.get("candidate_modules")
    if not isinstance(modules, list):
        modules = []
        errors.append("candidate_modules must be a list")
    module_ids = [m.get("id") for m in modules if isinstance(m, dict)]
    if (len(module_ids) != len(modules) or
            any(not isinstance(x, str) or not x for x in module_ids) or
            len(module_ids) != len(set(x for x in module_ids if isinstance(x, str)))):
        errors.append("duplicate or invalid native modules")
    for item in modules:
        if not isinstance(item, dict):
            continue
        for key in ("production_dispatch_migrated", "retire_legacy"):
            if type(item.get(key)) is not bool:
                errors.append(f"{item.get('id')}: {key} must be boolean")

    retiring = migration.get("retirement")
    if not isinstance(retiring, dict):
        retiring = {}
        errors.append("retirement must be an object")
    approved = retiring.get("approved_paths")
    if not isinstance(approved, list) or not all(isinstance(p, str) and p for p in approved):
        approved = []
        errors.append("approved_paths must be a list of nonempty paths")
    if len(set(approved)) != len(approved):
        errors.append("approved_paths contains duplicates")
    for path in approved:
        if (path.startswith("/") or "\\" in path or "\0" in path
                or path == ".git" or path.startswith(".git/")
                or any(part in ("", ".", "..") or part.casefold() == ".git" for part in path.split("/"))):
            errors.append(f"{path}: unsafe approved source path")
    for flag in ("production_dispatch_migrated", "whole_codex_rewritten"):
        mv, vv = migration.get(flag), verification.get(flag)
        if type(mv) is not bool or type(vv) is not bool or mv is not vv:
            errors.append(f"{flag}: migration and verification disagree or are non-boolean")

    if type(retiring.get("ready")) is not bool or type(verification.get("legacy_source_retired")) is not bool:
        errors.append("retirement readiness/retired claims must be boolean")
    incomplete = [
        c.get("id") for c in capabilities if isinstance(c, dict)
        and (c.get("migration_status") not in COMPLETE
             or c.get("production_dispatch_migrated") is not True)
    ]
    whole = migration.get("whole_codex_rewritten") is True
    dispatch = migration.get("production_dispatch_migrated") is True
    if whole and (not dispatch or incomplete):
        errors.append("whole-product rewrite claimed before every capability owns production dispatch")
    if dispatch and incomplete:
        errors.append("default production dispatch claimed while capability groups remain incomplete")
    if whole and migration.get("toolchain", {}).get("complete_compiler_runtime_qualified") is not True:
        errors.append("whole-product rewrite claimed without complete HIA compiler/runtime qualification")
    if whole and migration.get("current_qualification", {}).get("template_performance_closed") is not True:
        errors.append("whole-product rewrite claimed with unresolved template performance")
    if retiring.get("ready") is True and not (whole and dispatch and not incomplete):
        errors.append("retirement ready without whole-product/default-dispatch closure")
    if retiring.get("ready") is True and not approved:
        errors.append("retirement ready without approved source paths")
    if verification.get("legacy_source_retired") is True and retiring.get("ready") is not True:
        errors.append("legacy source claimed retired without retirement approval")
    if (verification.get("legacy_source_retired") is True
            and not any(isinstance(m, dict) and m.get("retire_legacy") is True for m in modules)):
        errors.append("legacy source claimed retired without a retired candidate module")

    if approved:
        records = retiring.get("per_path_qualification")
        if not isinstance(records, list):
            records = []
            errors.append("approved source paths require explicit per_path_qualification records")
        by_path = {r.get("path"): r for r in records if isinstance(r, dict)
                   and isinstance(r.get("path"), str)}
        for path in approved:
            record = by_path.get(path)
            if not record or not all(isinstance(record.get(k), str) and record[k]
                                     for k in ("source_tree", "qualification_sha256")):
                errors.append(f"{path}: missing immutable source-tree and qualification identities")
            if not record or not isinstance(record.get("verified_platforms"), list) or not record["verified_platforms"]:
                errors.append(f"{path}: missing executed platform qualification")
            elif (not all(isinstance(p, str) and p.strip() == p and p
                          for p in record["verified_platforms"])
                  or len(set(record["verified_platforms"])) != len(record["verified_platforms"])):
                errors.append(f"{path}: invalid executed platform qualification entries")
    # An approved deletion must not remove a shared Rust file still owned by
    # another active HIA candidate. A single migrated symbol does not retire
    # every other symbol in its source file.
    if retiring.get("ready") is True:
        for path in approved:
            owners = [m for m in modules if isinstance(m, dict)
                      and m.get("source_path") == path]
            if not owners:
                errors.append(f"{path}: no candidate module owns approved source deletion")
            elif any(m.get("retire_legacy") is not True
                     or m.get("production_dispatch_migrated") is not True
                     for m in owners):
                errors.append(f"{path}: shared source still has active or unqualified module owners")
    for item in modules:
        if isinstance(item, dict) and item.get("retire_legacy") is True:
            source = item.get("source_path")
            if not source or source not in approved:
                errors.append(f"{item.get('id')}: retire_legacy without an approved source path")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", type=Path, default=Path("hia/migration.json"))
    parser.add_argument("--verification", type=Path, default=Path("hia/verification.json"))
    args = parser.parse_args()
    try:
        migration = json.loads(args.migration.read_text(encoding="utf-8"))
        verification = json.loads(args.verification.read_text(encoding="utf-8"))
        errors = validate(migration, verification)
    except (OSError, ValueError, TypeError) as exc:
        print(f"HIA migration invariant error: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"HIA migration invariant error: {error}")
        return 1
    print("HIA migration declarations internally consistent (not whole-product qualification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
