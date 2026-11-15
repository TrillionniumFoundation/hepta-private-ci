#!/usr/bin/env python3
"""Fail-closed, read-only whole-Codex HIA retirement eligibility checker.

This script never deletes files or promotes a release. Its successful result is
only a prerequisite to a separately authorized source-retirement operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

EXPECTED_CAPABILITIES = frozenset({
    "model_transport", "authentication_identity", "thread_turn_execution",
    "history_storage_recovery", "tools_processes_files", "permissions_sandbox",
    "mcp", "app_server_v2", "cli_tui", "sdk_frontends",
    "patch_application", "string_utilities", "hepta_cells_and_adapters",
    "platforms_build_release", "hia_toolchain",
})
EXPECTED_MANIFEST_COUNT = 198
EXPECTED_BASELINE_INVENTORY_SHA256 = "9df5ab92ad68f36293bba6b1198c9074689f0acb09f7717f5554bb41f169dfd8"
EXPECTED_MODULE_IDS = frozenset({
    "seek_sequence", "utf8_boundaries", "utf8_prefix", "metric_tag",
    "markdown_location", "ascii_json_fragment", "uuid_matches",
    "template_parser", "template_render", "template_index", "prefix_match",
    "prefix_admission", "policy_summary", "network_domains",
    "allowed_prefixes", "command_dispatch", "network_host",
})
REQUIRED_FLAGS = (
    "whole_codex_rewritten", "production_dispatch_migrated",
    "default_release_migrated", "workspace_qualified",
    "performance_qualified",
)
REQUIRED_PLATFORMS = frozenset({
    "linux-x86_64-gnu", "linux-aarch64-gnu",
    "macos-x86_64", "macos-aarch64",
    "windows-x86_64-msvc", "windows-aarch64-msvc",
})
REQUIRED_RETIREMENT_REQUIREMENTS = (
    "HIA owns the actual production dispatch and effects for the replaced scope",
    "original Rust behavior and malformed-input cases pass without skipped or substituted oracles",
    "existing protocol, CLI, configuration, persisted-session and SDK interfaces remain compatible",
    "required platforms and app/exec host combinations pass",
    "clean build, package installation and end-to-end use pass on the resulting source tree",
    "regression fixtures, licensing and required release assets remain available",
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular, non-symlink file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, timeout=15,
    )
    return result.stdout.strip()


def _full_true(obj: dict, key: str) -> bool:
    return obj.get(key) is True


def _has_exact_qualified_ids(rows: object, expected: frozenset[str], *, kind: str,
                             problems: list[str]) -> None:
    if not isinstance(rows, list):
        problems.append(f"{kind}: missing list")
        return
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if (len(ids) != len(rows) or any(not isinstance(v, str) for v in ids)
            or len(ids) != len(set(v for v in ids if isinstance(v, str)))
            or set(v for v in ids if isinstance(v, str)) != expected):
        problems.append(f"{kind}: missing, unexpected, or duplicated identities")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("migration_status") != "qualified_native":
            problems.append(f"{kind}/{row.get('id')}: not qualified_native")
        if not _full_true(row, "production_dispatch_migrated"):
            problems.append(f"{kind}/{row.get('id')}: production dispatch not migrated")


def _safe_retirement_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    candidate = PurePosixPath(value)
    if (candidate.is_absolute() or value != candidate.as_posix()
            or value in (".", "..") or not candidate.parts
            or any(part in (".", "..", ".git") for part in candidate.parts)
            or candidate.parts[0] in ("hia", ".github", "AGENTS.md", "LICENSE", "NOTICE")):
        return False
    return ":" not in candidate.parts[0]


def check(repo: Path, migration_path: Path, evidence_path: Path) -> dict:
    problems: list[str] = []
    try:
        migration = _json(migration_path)
        head = _git(repo, "rev-parse", "HEAD")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        if _git(repo, "status", "--porcelain", "--untracked-files=no"):
            problems.append("tracked worktree/index is dirty")
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {"ready": False, "problems": [f"unverifiable inputs: {error}"]}

    try:
        evidence = _json(evidence_path)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        evidence = {}
        problems.append(f"retirement evidence unavailable: {error}")

    if migration.get("schema") != "codex.hia.migration.v1":
        problems.append("migration schema is not recognized")
    for key in REQUIRED_FLAGS:
        if not _full_true(migration, key):
            problems.append(f"{key} is not true")
    retirement = migration.get("retirement")
    if not isinstance(retirement, dict) or retirement.get("ready") is not True:
        problems.append("retirement.ready is not true")
    if migration.get("legacy_source_retired") is not False:
        problems.append("legacy_source_retired must be false before retirement")
    approved_paths = retirement.get("approved_paths") if isinstance(retirement, dict) else None
    if not isinstance(approved_paths, list) or not approved_paths:
        problems.append("retirement.approved_paths is empty")
    else:
        if any(not _safe_retirement_path(v) for v in approved_paths):
            problems.append("retirement.approved_paths contains an unsafe path")
        if len(set(v for v in approved_paths if isinstance(v, str))) != len(approved_paths):
            problems.append("retirement.approved_paths contains duplicates")

    caps = migration.get("capabilities")
    _has_exact_qualified_ids(caps, EXPECTED_CAPABILITIES,
                             kind="capability", problems=problems)

    baseline = migration.get("baseline")
    manifests = migration.get("rust_components")
    expected_count = baseline.get("codex_rs_cargo_manifest_count") if isinstance(baseline, dict) else None
    if not isinstance(baseline, dict) or baseline.get("inventory_sha256") != EXPECTED_BASELINE_INVENTORY_SHA256:
        problems.append("original baseline inventory digest changed")
    if expected_count != EXPECTED_MANIFEST_COUNT:
        problems.append("original baseline Cargo manifest count changed")
    if not isinstance(manifests, list) or type(expected_count) is not int or expected_count < 1:
        problems.append("Rust inventory is missing or malformed")
    else:
        paths = [v.get("manifest") for v in manifests if isinstance(v, dict)]
        if (len(paths) != len(manifests) or any(not isinstance(v, str) for v in paths)
                or len(paths) != len(set(v for v in paths if isinstance(v, str)))
                or len(paths) != expected_count):
            problems.append("Rust inventory is incomplete or duplicated")
        for v in manifests:
            if not isinstance(v, dict):
                continue
            if v.get("migration_status") != "qualified_native" or v.get("production_dispatch_migrated") is not True:
                problems.append(f"Rust manifest not migrated: {v.get('manifest')}")

    modules = migration.get("candidate_modules")
    if not isinstance(modules, list) or not modules:
        problems.append("candidate_modules is empty")
    else:
        ids = [v.get("id") for v in modules if isinstance(v, dict)]
        if (len(ids) != len(modules) or any(not isinstance(v, str) for v in ids)
                or len(ids) != len(set(v for v in ids if isinstance(v, str)))
                or not EXPECTED_MODULE_IDS.issubset(set(v for v in ids if isinstance(v, str)))):
            problems.append("candidate_modules contains missing, invalid, or duplicate identities")
        for v in modules:
            if not isinstance(v, dict):
                continue
            if v.get("production_dispatch_migrated") is not True or v.get("retire_legacy") is not True:
                problems.append(f"candidate still uses a legacy owner: {v.get('id')}")

    if evidence.get("schema") != "codex.hia.retirement-evidence.v1":
        problems.append("retirement evidence schema is not recognized")
    if evidence.get("source_revision") != head or not HEX40.fullmatch(head):
        problems.append("evidence source_revision does not match checked-out Git HEAD")
    if evidence.get("source_tree") != tree or not HEX40.fullmatch(tree):
        problems.append("evidence source_tree does not match checked-out Git tree")
    platforms = evidence.get("platforms")
    if (not isinstance(platforms, list) or any(not isinstance(v, str) for v in platforms)
            or len(platforms) != len(set(v for v in platforms if isinstance(v, str)))
            or set(v for v in platforms if isinstance(v, str)) != REQUIRED_PLATFORMS):
        problems.append("required Linux/macOS/Windows architecture matrix is incomplete")
    requirements = retirement.get("requirements") if isinstance(retirement, dict) else None
    attestations = evidence.get("requirements")
    if requirements != list(REQUIRED_RETIREMENT_REQUIREMENTS):
        problems.append("canonical retirement requirements were changed or weakened")
    if not isinstance(requirements, list) or len(requirements) != 6 or not isinstance(attestations, list) or len(attestations) != 6:
        problems.append("six source-bound retirement requirement attestations are required")
    else:
        seen = set()
        for item in attestations:
            if not isinstance(item, dict):
                problems.append("malformed requirement attestation")
                continue
            idx = item.get("index")
            if type(idx) is not int or idx < 0 or idx >= 6 or idx in seen:
                problems.append("missing, duplicate or out-of-range requirement index")
                continue
            seen.add(idx)
            if item.get("requirement") != requirements[idx] or item.get("status") != "passed":
                problems.append(f"requirement {idx} not passed on unchanged contract")
            path = item.get("artifact")
            digest = item.get("sha256")
            if not isinstance(path, str) or not isinstance(digest, str) or not HEX64.fullmatch(digest):
                problems.append(f"requirement {idx} lacks an exact evidence file/digest")
                continue
            target = repo / path
            try:
                if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(repo.resolve()):
                    raise ValueError("not a regular in-repository file")
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError("digest mismatch")
            except (OSError, ValueError) as error:
                problems.append(f"requirement {idx} evidence invalid: {error}")
        if seen != set(range(6)):
            problems.append("one or more of the six attestation indices is missing")
    return {"ready": not problems, "head": head, "tree": tree,
            "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--migration", type=Path, default=Path("hia/migration.json"))
    parser.add_argument("--evidence", type=Path, default=Path("hia/retirement-evidence.json"),
                        help="exact source-bound release evidence; absence fails closed")
    args = parser.parse_args()
    repo = args.repo.resolve()
    migration = args.migration if args.migration.is_absolute() else repo / args.migration
    evidence = args.evidence if args.evidence.is_absolute() else repo / args.evidence
    report = check(repo, migration, evidence)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
