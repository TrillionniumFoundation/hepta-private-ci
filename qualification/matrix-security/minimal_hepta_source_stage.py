#!/usr/bin/env python3
"""Build a disposable Hepta Matrix adapter candidate from exactly pinned source.

This prepares NO production artifact. It uses the existing audited upstream
0.19.1 + AnyMap3 migration stage and changes only one detached Hepta worktree
manifest. Cargo metadata/check/deny and real WAL/E2EE remain separate gates.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from disposable_backport_probe import stage_candidate
from staged_resolution_probe import SOURCE_SPEC, SQLITE_PATCH_SPEC

SCHEMA = "hepta.matrix-minimal-hepta-0.19-anymap3-stage.v1"
ORIGINAL_MATRIX = {
    "version": "0.18.0",
    "default-features": False,
    "features": ["e2e-encryption", "sqlite"],
}


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _git(root, *parts):
    result = subprocess.run(
        ["git", "-C", str(root), *parts], capture_output=True, text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("detached candidate Git identity unavailable")
    return result.stdout.strip()


def rewrite_manifest(original, cargo_dir, minimal_source):
    """Construct the exact, single-mutation candidate for a local SDK source.

    It is intentionally path-based so the compiler reads only the verified
    minimal upstream patch, not a 278-commit later development revision.
    """
    if type(original) is not bytes:
        raise ValueError("manifest source must be immutable bytes")
    try:
        source = original.decode("utf-8")
        manifest = tomllib.loads(source)
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("unparsable original manifest") from error
    candidate = Path(minimal_source).resolve()
    cargo_dir = Path(cargo_dir).resolve()
    if candidate == cargo_dir or candidate in cargo_dir.parents or cargo_dir in candidate.parents:
        raise ValueError("source candidate must be external to Hepta worktree")
    if not (candidate / "crates/matrix-sdk").is_dir():
        raise ValueError("missing independently staged Matrix source")
    if manifest.get("workspace", {}).get("dependencies", {}).get("matrix-sdk") != ORIGINAL_MATRIX:
        raise ValueError("original Matrix SDK dependency baseline changed")
    if manifest.get("patch", {}).get("crates-io", {}).get("matrix-sdk-sqlite") != {
        "path": "third_party/matrix-sdk-sqlite-0.18.0"
    }:
        raise ValueError("original SQLite patch identity changed")
    if source.count(SOURCE_SPEC) != 1 or source.count(SQLITE_PATCH_SPEC + "\n") != 1:
        raise ValueError("cannot replace exactly one frozen Matrix SDK/SQLite clause")
    sdk_path = os.path.relpath(candidate / "crates/matrix-sdk", cargo_dir).replace(os.sep, "/")
    if not sdk_path.startswith("../") or '"' in sdk_path or "\n" in sdk_path:
        raise ValueError("candidate path is not isolated and safely encodable")
    replacement = (
        'matrix-sdk = { path = "' + sdk_path + '", '
        'default-features = false, features = ["e2e-encryption", "sqlite"] }'
    )
    staged = source.replace(SOURCE_SPEC, replacement, 1).replace(
        SQLITE_PATCH_SPEC + "\n", "", 1,
    )
    try:
        doc = tomllib.loads(staged)
    except tomllib.TOMLDecodeError as error:
        raise ValueError("candidate TOML became invalid") from error
    if doc["workspace"]["dependencies"]["matrix-sdk"] != {
        "path": sdk_path, "default-features": False,
        "features": ["e2e-encryption", "sqlite"],
    } or "matrix-sdk-sqlite" in doc.get("patch", {}).get("crates-io", {}):
        raise ValueError("unexpected Matrix feature or SQLite patch drift")
    return staged.encode("utf-8")


def prepare(stage, release, migration, candidate_dir, source_sha, *, source_builder=stage_candidate):
    stage = Path(stage).resolve()
    candidate_dir = Path(candidate_dir).resolve()
    release = Path(release).resolve()
    migration = Path(migration).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("invalid exact PR source SHA")
    if not stage.is_dir() or stage == release or stage == migration:
        raise ValueError("missing separate detached Hepta worktree")
    if candidate_dir.exists() or candidate_dir.parent != stage.parent:
        raise ValueError("new patched SDK must be a sibling of detached Hepta worktree")
    if _git(stage, "rev-parse", "HEAD") != source_sha or _git(stage, "status", "--porcelain"):
        raise ValueError("Hepta worktree dirty or not at exact source HEAD")
    manifest_path = stage / "codex-rs/Cargo.toml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest must be an ordinary tracked candidate file")
    original = manifest_path.read_bytes()
    # This guard runs BEFORE any artifact source is copied or mutated.
    if original != subprocess.run(
        ["git", "-C", str(stage), "show", "HEAD:codex-rs/Cargo.toml"],
        capture_output=True, check=True,
    ).stdout:
        raise ValueError("candidate manifest differs from pinned Git revision")
    # The only source mutation is inside candidate_dir, never under release.
    verified = source_builder(release, migration, candidate_dir)
    if verified.get("anymap2_source_dependency_removed") is not True or verified.get("production_authorized") is not False:
        raise ValueError("unverified minimal upstream source candidate")
    candidate_manifest = candidate_dir / "crates/matrix-sdk/Cargo.toml"
    upstream = tomllib.loads(candidate_manifest.read_text(encoding="utf-8"))
    if (upstream.get("package", {}).get("version") != "0.19.1"
            or "anymap2" in upstream.get("dependencies", {})
            or "anymap3" not in upstream.get("dependencies", {})):
        raise ValueError("minimal SDK candidate has unreviewed dependencies")
    rewritten = rewrite_manifest(original, stage / "codex-rs", candidate_dir)
    manifest_path.write_bytes(rewritten)
    if _git(stage, "diff", "--name-only") != "codex-rs/Cargo.toml":
        raise ValueError("candidate worktree modified more than its Matrix manifest")
    return {
        "schema": SCHEMA,
        "hepta_source_sha": source_sha,
        "signed_upstream_release_sha": verified["release_commit"],
        "upstream_anymap_change_sha": verified["migration_commit"],
        "minimal_upstream_patch_sha256": verified["applied_source_patch_sha256"],
        "hepta_manifest_before_sha256": _sha(original),
        "hepta_candidate_manifest_sha256": _sha(rewritten),
        "sqlite_arm": "genuine_upstream_0_19_sqlite",
        "sdk_source_root": str(candidate_dir),
        "matrix_sdk_manifest": str(candidate_manifest),
        "cargo_resolution_verified": False,
        "hepta_matrix_compile_verified": False,
        "matrix_e2ee_verified": False,
        "sqlite_wal_recovery_verified": False,
        "cargo_deny_verified": False,
        "production_source_modified": False,
        "production_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    if out.exists() or any(out.is_relative_to(p.resolve()) for p in (args.stage, args.release, args.migration)):
        parser.error("report must be new and external to audited source checkouts")
    report = prepare(args.stage, args.release, args.migration, args.candidate_dir, args.source_sha)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
