#!/usr/bin/env python3
"""Read-only, exact-commit proof for the narrow Matrix SDK anymap3 backport.

The published SDK 0.19.1 still contains anymap2. Its upstream replacement is
an independently identifiable three-file commit. This probe checks whether the
TWO source hunks from that commit apply to the pinned release WITHOUT running
foreign code, amending source, resolving dependencies, or granting authority.

A clean patch is only a candidate for full security review and Rust/SQLite/E2EE
qualification; it is not a license to patch Cargo.lock or promote production.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

RELEASE_SHA = "b18166c68bb958a21f0bca8b2d8320cb53583362"
MIGRATION_SHA = "9c5fdd2cf5be1b7b8b20541e56d7a109db968534"
CHANGESET = frozenset({
    "Cargo.lock",
    "crates/matrix-sdk/Cargo.toml",
    "crates/matrix-sdk/src/event_handler/mod.rs",
})
SOURCE_FILES = (
    "crates/matrix-sdk/Cargo.toml",
    "crates/matrix-sdk/src/event_handler/mod.rs",
)
MAX_PATCH_BYTES = 128 * 1024


def git(root, *args, input_bytes=None):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes, capture_output=True, check=False,
    )


def stdout_checked(result, description):
    if result.returncode != 0:
        raise ValueError(f"{description} failed")
    return result.stdout.decode("utf-8", errors="strict").strip()


def probe(release, migration, *, release_sha=RELEASE_SHA, migration_sha=MIGRATION_SHA):
    release, migration = Path(release).resolve(), Path(migration).resolve()
    if release == migration or release in migration.parents or migration in release.parents:
        raise ValueError("release and migration must be separate, immutable checkouts")
    for value in (release_sha, migration_sha):
        if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("expected commit SHA must be fixed, lowercase hex")
    for root, expected, label in (
        (release, release_sha, "published release"),
        (migration, migration_sha, "upstream patch"),
    ):
        observed = stdout_checked(git(root, "rev-parse", "HEAD"), f"{label} HEAD")
        if observed != expected:
            raise ValueError(f"{label} is not the expected immutable commit")
        if git(root, "status", "--porcelain").stdout.strip():
            raise ValueError(f"{label} checkout is dirty")

    changed = stdout_checked(
        git(migration, "diff-tree", "--no-commit-id", "--name-only", "-r", migration_sha),
        "upstream change inventory",
    ).splitlines()
    if frozenset(changed) != CHANGESET or len(changed) != len(CHANGESET):
        raise ValueError("upstream patch changed unexpected files")

    manifest = tomllib.loads((release / SOURCE_FILES[0]).read_text(encoding="utf-8"))
    if manifest["package"]["version"] != "0.19.1":
        raise ValueError("published Matrix SDK version is not exactly 0.19.1")
    if "anymap2" not in manifest.get("dependencies", {}) or "anymap3" in manifest.get("dependencies", {}):
        raise ValueError("released source does not have the expected vulnerable baseline")
    source = (release / SOURCE_FILES[1]).read_text(encoding="utf-8")
    if "anymap2::" not in source:
        raise ValueError("published event-handler implementation has unexpected shape")

    patch = git(migration, "show", "--format=", "--no-ext-diff", "--binary", migration_sha, "--", *SOURCE_FILES)
    if patch.returncode != 0 or not 0 < len(patch.stdout) <= MAX_PATCH_BYTES:
        raise ValueError("upstream source patch is unavailable or oversized")
    if b"anymap3" not in patch.stdout or b"anymap2" not in patch.stdout:
        raise ValueError("upstream source patch does not change the advertised AnyMap dependency")
    check = git(release, "apply", "--check", "-", input_bytes=patch.stdout)
    if git(release, "status", "--porcelain").stdout.strip():
        raise ValueError("read-only patch check modified the published release")
    return {
        "schema": "hepta.matrix-sdk-minimal-anymap-backport.v1",
        "published_release_commit": release_sha,
        "upstream_anymap3_commit": migration_sha,
        "upstream_commit_changed_files": sorted(changed),
        "source_patch_files": list(SOURCE_FILES),
        "source_patch_sha256": hashlib.sha256(patch.stdout).hexdigest(),
        "source_patch_bytes": len(patch.stdout),
        "source_patch_applies_clean": check.returncode == 0,
        "git_apply_check_exit_code": check.returncode,
        "git_apply_diagnostic": check.stderr.decode("utf-8", errors="replace")[-1800:],
        "execution_performed": False,
        "compiled_upstream": False,
        "source_security_review_approved": False,
        "cargo_graph_resolution_verified": False,
        "sqlite_wal_compatibility_verified": False,
        "matrix_e2ee_verified": False,
        "cargo_deny_verified": False,
        "production_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = probe(args.release, args.migration)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    # A patch that does not apply to the pinned release is a failed source
    # qualification, not a diagnostic success or an advisory waiver.
    return 0 if report["source_patch_applies_clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
