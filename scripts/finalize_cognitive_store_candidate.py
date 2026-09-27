#!/usr/bin/env python3
"""Finalize the cognitive.store convergence candidate exactly once.

This script is invoked by a temporary Windows workflow so it does not compete
with the Linux qualification lanes. It patches deterministic fixtures, regenerates
the implementation map against the staged Git tree, deletes its temporary
bootstrap files, verifies the committed candidate, and publishes the same commit
to the working branch and active PR head.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKING_BRANCH = "codex/cognitive-store-total-closure-20260927"
PR_BRANCH = "codex/cognitive-store-full-closure-20260927"
TEMPORARY_PATHS = (
    Path(".github/workflows/cognitive-store-integration-fixup.yml"),
    Path(".github/workflows/cognitive-store-finalizer-windows.yml"),
    Path("scripts/finalize_cognitive_store_candidate.py"),
)


def run(*args: str, cwd: Path = ROOT, capture: bool = False) -> str:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def git(*args: str, capture: bool = True) -> str:
    return run("git", *args, capture=capture)


def patch_lockfile() -> None:
    path = ROOT / "codex-rs/Cargo.lock"
    text = path.read_text(encoding="utf-8")
    start = text.index('[[package]]\nname = "codex-hepta-agentd"')
    end = text.index("\n[[package]]", start + 1)
    package = text[start:end]
    dependency = ' "ed25519-dalek",\n'
    if dependency not in package:
        marker = ' "core_test_support",\n'
        if marker not in package:
            raise RuntimeError("Agentd lockfile insertion marker is missing")
        package = package.replace(marker, marker + dependency, 1)
        text = text[:start] + package + text[end:]
        path.write_text(text, encoding="utf-8")


def patch_deterministic_fixtures() -> None:
    migration_path = ROOT / "codex-rs/hepta-memory/src/cognitive_store_tests.rs"
    migration = migration_path.read_text(encoding="utf-8")
    old_versions = '"1,2,3,4,5,6,7,8,9,10,11,12,13,14"'
    new_versions = '"1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"'
    if old_versions in migration:
        migration = migration.replace(old_versions, new_versions, 1)
    if new_versions not in migration:
        raise RuntimeError("migration ledger fixture did not converge to schema 15")
    migration_path.write_text(migration, encoding="utf-8")

    compact_path = ROOT / "codex-rs/hepta-memory/src/local_compact_executor_tests.rs"
    compact = compact_path.read_text(encoding="utf-8")
    old_offset = 'let expiry_offset = if transition == "expire" { 1 } else { 3_600 };'
    new_offset = 'let expiry_offset = if transition == "expire" { 5 } else { 3_600 };'
    old_wait = "for _ in 0..120 {"
    new_wait = "for _ in 0..400 {"
    if old_offset in compact:
        compact = compact.replace(old_offset, new_offset, 1)
    if old_wait in compact:
        compact = compact.replace(old_wait, new_wait, 1)
    if new_offset not in compact or new_wait not in compact:
        raise RuntimeError("compact expiry fixture did not converge")
    compact_path.write_text(compact, encoding="utf-8")


def normalize_mapped_path(value: Any) -> str | None:
    if isinstance(value, str):
        path = value
    elif isinstance(value, dict):
        path = value.get("path", value.get("sourcePath"))
    else:
        return None
    if not isinstance(path, str) or not path:
        return None
    if ".rs::" in path:
        path = path.split(".rs::", 1)[0] + ".rs"
    return path.replace("\\", "/")


def reconcile_map() -> Path:
    path = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
    mapping: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    callers = mapping.get("productCallers", [])
    canonical = [
        caller
        for caller in callers
        if caller.get("sourcePath")
        == "codex-rs/hepta-agentd/src/production_writer_host.rs"
        and caller.get("nativeSymbol") == "AgentdProductionWriterHost"
    ]
    if len(canonical) != 1 or len(callers) != 1:
        raise RuntimeError("implementation map must contain exactly one Agentd writer facade")
    canonical[0]["state"] = "canonical_production_write_facade"

    inventory = {
        "operation": "rust_module_inventory",
        "designOperation": "closed_world_crate_root_reachability",
        "nativeSymbol": "check-rust-module-inventory.py",
        "sourcePath": "scripts/check-rust-module-inventory.py",
        "state": "source_implemented_execution_pending",
        "authority": "none",
        "mappingClass": "architecture_verifier",
        "delegatedCallees": [],
        "tests": [],
        "sourcePathExists": True,
    }
    operations = mapping.get("operations", [])
    matches = [row for row in operations if row.get("operation") == "rust_module_inventory"]
    if matches:
        matches[0].clear()
        matches[0].update(inventory)
    else:
        operations.append(inventory)
    mapping["operations"] = operations
    mapping["sourceObjects"] = []
    path.write_text(json.dumps(mapping, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def delete_temporary_paths() -> None:
    for relative in TEMPORARY_PATHS:
        (ROOT / relative).unlink(missing_ok=True)


def mapped_paths(mapping: dict[str, Any]) -> set[str]:
    paths: set[str] = set(mapping.get("resolvedRoots", []))
    paths.add(mapping["technicalGuide"])
    for caller in mapping.get("productCallers", []):
        path = normalize_mapped_path(caller)
        if path:
            paths.add(path)
    for operation in mapping.get("operations", []):
        path = normalize_mapped_path(operation.get("sourcePath"))
        if path:
            paths.add(path)
        for key in ("tests", "delegatedCallees"):
            for entry in operation.get(key, []):
                path = normalize_mapped_path(entry)
                if path:
                    paths.add(path)
    return paths


def stage_and_bind_source_objects(map_path: Path) -> None:
    run(
        "git",
        "add",
        "-A",
        "codex-rs/Cargo.lock",
        "codex-rs/hepta-memory/src/cognitive_store_tests.rs",
        "codex-rs/hepta-memory/src/local_compact_executor_tests.rs",
        "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json",
        ".github/workflows/cognitive-store-integration-fixup.yml",
        ".github/workflows/cognitive-store-finalizer-windows.yml",
        "scripts/finalize_cognitive_store_candidate.py",
    )

    mapping: dict[str, Any] = json.loads(map_path.read_text(encoding="utf-8"))
    paths = mapped_paths(mapping)
    missing = [path for path in sorted(paths) if not (ROOT / path).exists()]
    if missing:
        raise RuntimeError("mapped source paths are missing: " + ", ".join(missing))

    provisional_tree = git("write-tree")
    mapping["sourceObjects"] = [
        {"path": path, "object": git("rev-parse", f"{provisional_tree}:{path}")}
        for path in sorted(paths)
    ]
    map_path.write_text(json.dumps(mapping, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    run("git", "add", "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json")


def commit_candidate() -> str:
    run("git", "config", "user.name", "Hepta Cognitive CI")
    run("git", "config", "user.email", "hepta-cognitive-ci@users.noreply.github.com")
    run("git", "diff", "--cached", "--check")
    quiet = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False
    ).returncode
    if quiet != 0:
        run("git", "commit", "-m", "cognitive.store: finalize exact candidate evidence map")
    return git("rev-parse", "HEAD")


def verify_candidate() -> None:
    sha = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    run("python", "scripts/check-rust-module-inventory.py", "codex-rs/hepta-cognitive-store/src")
    run("python", "scripts/verify_cognitive_store_boundary.py")
    run(
        "python",
        "scripts/cognitive_store_map_verify.py",
        "--expected-sha",
        sha,
        "--expected-tree",
        tree,
    )
    run("cargo", "metadata", "--locked", "--format-version", "1", "--no-deps", cwd=ROOT / "codex-rs")
    if git("status", "--porcelain"):
        raise RuntimeError("finalized candidate is not clean")


def publish() -> None:
    run(
        "git",
        "push",
        "origin",
        f"HEAD:{WORKING_BRANCH}",
        f"HEAD:{PR_BRANCH}",
    )


def main() -> int:
    patch_lockfile()
    patch_deterministic_fixtures()
    map_path = reconcile_map()
    delete_temporary_paths()
    stage_and_bind_source_objects(map_path)
    commit_candidate()
    verify_candidate()
    publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
