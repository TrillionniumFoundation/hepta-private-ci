#!/usr/bin/env python3
"""Stage one exact AnyMap3 source backport in an isolated, disposable clone.

The verified SDK 0.19.1 release and pinned upstream migration checkouts remain
untouched. A staged patch does NOT pass cargo-deny, E2EE, WAL recovery, or
production admission. All upstream source identity checks are delegated to
minimal_backport_probe.probe and cannot be bypassed by command-line flags.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

from minimal_backport_probe import (
    MAX_PATCH_BYTES,
    MIGRATION_SHA,
    RELEASE_SHA,
    SOURCE_FILES,
    _release_specific_source_patch,
    git,
    probe,
)


def stage_candidate(release, migration, destination, *, release_sha=RELEASE_SHA,
                    migration_sha=MIGRATION_SHA):
    release, migration = Path(release).resolve(), Path(migration).resolve()
    destination = Path(destination).resolve()
    if (destination.exists()
            or release == destination
            or migration == destination
            or release in destination.parents
            or migration in destination.parents
            or destination in release.parents
            or destination in migration.parents):
        raise ValueError("candidate must use a new, separate disposable checkout")
    # Run the exact-commit/source-inventory/patch-shape/clean-tree qualification
    # BEFORE allocating or modifying a candidate checkout.
    verified = probe(release, migration, release_sha=release_sha,
                     migration_sha=migration_sha)
    if not verified["source_patch_applies_clean"]:
        raise ValueError("pinned source patch does not apply to audited release")
    upstream = git(migration, "show", "--format=", "--no-ext-diff", "--binary",
                   migration_sha, "--", *SOURCE_FILES)
    if upstream.returncode != 0 or not 0 < len(upstream.stdout) <= MAX_PATCH_BYTES:
        raise ValueError("cannot recover pinned upstream source delta")
    patch = _release_specific_source_patch(release, upstream.stdout)
    if hashlib.sha256(patch).hexdigest() != verified["source_patch_sha256"]:
        raise ValueError("upstream translation digest changed between checks")

    # No hardlinked Git objects, no git worktree metadata written to the
    # independently audited release. The new clone is never merged back.
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--local", "--no-hardlinks",
         "--no-checkout", "--", str(release), str(destination)],
        capture_output=True, check=False,
    )
    if clone.returncode != 0:
        raise ValueError("disposable release clone failed")
    checkout = git(destination, "checkout", "--quiet", "--detach", release_sha)
    if checkout.returncode != 0:
        raise ValueError("disposable checkout cannot bind release SHA")
    head = git(destination, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.decode().strip() != release_sha:
        raise ValueError("cloned release commit differs from fixed upstream")
    if git(destination, "status", "--porcelain").stdout.strip():
        raise ValueError("disposable checkout unexpectedly dirty")

    check = git(destination, "apply", "--check", "-", input_bytes=patch)
    if check.returncode != 0:
        raise ValueError("verified source patch changed before isolated application")
    applied = git(destination, "apply", "-", input_bytes=patch)
    if applied.returncode != 0:
        raise ValueError("isolated source patch application failed")
    diff = git(destination, "diff", "--name-only", "--")
    if diff.returncode != 0 or set(diff.stdout.decode().splitlines()) != set(SOURCE_FILES):
        raise ValueError("staged source changed outside exact two-file AnyMap profile")
    manifest = tomllib.loads(
        (destination / SOURCE_FILES[0]).read_text(encoding="utf-8")
    )
    deps = manifest.get("dependencies", {})
    code = (destination / SOURCE_FILES[1]).read_text(encoding="utf-8")
    if (manifest.get("package", {}).get("version") != "0.19.1"
            or "anymap2" in deps or "anymap3" not in deps
            or "anymap2::" in code or "anymap3::" not in code):
        raise ValueError("staged source still depends on obsolete AnyMap")
    for root in (release, migration):
        result = git(root, "status", "--porcelain")
        if result.returncode != 0 or result.stdout.strip():
            raise ValueError("audited upstream source mutated by disposable candidate")

    return {
        "schema": "hepta.matrix-disposable-anymap3-source.v1",
        "release_commit": release_sha,
        "migration_commit": migration_sha,
        "applied_source_patch_sha256": verified["source_patch_sha256"],
        "changed_source_files": list(SOURCE_FILES),
        "anymap2_source_dependency_removed": True,
        "disposable_git_head": release_sha,
        "cargo_resolution_verified": False,
        "cargo_deny_verified": False,
        "e2ee_crypto_verified": False,
        "sqlite_wal_recovery_verified": False,
        "independent_security_review_approved": False,
        "production_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = stage_candidate(args.release, args.migration, args.destination)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
