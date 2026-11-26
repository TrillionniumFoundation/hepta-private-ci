#!/usr/bin/env python3
"""Read-only, exact-commit proof for the narrow Matrix SDK anymap3 backport.

The published SDK 0.19.1 still contains anymap2. Its upstream replacement is
an independently identifiable three-file commit. This probe checks whether the
FOUR source replacement blocks from that commit apply to the pinned release WITHOUT running
foreign code, amending source, resolving dependencies, or granting authority.

A clean patch is only a candidate for full security review and Rust/SQLite/E2EE
qualification; it is not a license to patch Cargo.lock or promote production.
"""

import argparse
import difflib
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


def _source_change_blocks(source_diff):
    """Extract only contiguous AnyMap substitutions from a PINNED Git diff.

    Context lines are intentionally ignored in the transformed delta. Upstream
    added unrelated manifest dependencies after the signed release; repeating
    newer context would make an otherwise minimal backport fail to apply.
    """
    changes = {path: [] for path in SOURCE_FILES}
    current_path = None
    old_lines, new_lines = [], []

    def flush():
        if not old_lines and not new_lines:
            return
        if (current_path not in changes or not old_lines or not new_lines
                or "anymap2" not in "".join(old_lines)
                or "anymap3" not in "".join(new_lines)):
            raise ValueError("unexpected non-AnyMap source mutation in upstream patch")
        changes[current_path].append(("".join(old_lines), "".join(new_lines)))
        old_lines.clear()
        new_lines.clear()

    for line in source_diff.decode("utf-8", errors="strict").splitlines(keepends=True):
        if line.startswith("diff --git a/"):
            flush()
            names = line.rstrip("\n").split(" ")
            if len(names) != 4 or not names[3].startswith("b/"):
                raise ValueError("malformed pinned upstream Git diff")
            current_path = names[3][2:]
            if current_path not in changes or names[2] != "a/" + current_path:
                raise ValueError("unexpected upstream diff source path")
        elif line.startswith("@@") or line.startswith(" "):
            flush()
        elif line.startswith("--- ") or line.startswith("+++ "):
            flush()
        elif line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        else:
            flush()
    flush()
    if (len(changes[SOURCE_FILES[0]]) != 1 or
            len(changes[SOURCE_FILES[1]]) != 3):
        raise ValueError("upstream AnyMap source blocks differ from pinned 1+3 profile")
    return changes


def _release_specific_source_patch(release, source_diff):
    changes = _source_change_blocks(source_diff)
    translated = []
    for path in SOURCE_FILES:
        original = (release / path).read_text(encoding="utf-8")
        altered = original
        for old, new in changes[path]:
            if altered.count(old) != 1:
                raise ValueError("published release incompatible with exact upstream AnyMap change")
            altered = altered.replace(old, new, 1)
        if altered == original or "anymap2::" in altered:
            raise ValueError("unresolved obsolete AnyMap implementation in translated release")
        source_delta = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), altered.splitlines(keepends=True),
            fromfile="a/" + path, tofile="b/" + path, n=3,
        ))
        translated.append("diff --git a/" + path + " b/" + path + "\n" + source_delta)
    output = "".join(translated).encode("utf-8")
    if not 0 < len(output) <= MAX_PATCH_BYTES:
        raise ValueError("release-specific patch is unavailable or oversized")
    return output


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
    raw_check = git(release, "apply", "--check", "-", input_bytes=patch.stdout)
    # A context mismatch in upstream's later manifest is *not* permission to
    # import hundreds of unrelated mainline commits. Translate ONLY the four
    # exact upstream AnyMap substitutions onto the immutable release contents.
    release_patch = _release_specific_source_patch(release, patch.stdout)
    check = git(release, "apply", "--check", "-", input_bytes=release_patch)
    if git(release, "status", "--porcelain").stdout.strip():
        raise ValueError("read-only patch check modified the published release")
    return {
        "schema": "hepta.matrix-sdk-minimal-anymap-backport.v2",
        "published_release_commit": release_sha,
        "upstream_anymap3_commit": migration_sha,
        "upstream_commit_changed_files": sorted(changed),
        "source_patch_files": list(SOURCE_FILES),
        "upstream_source_patch_sha256": hashlib.sha256(patch.stdout).hexdigest(),
        "upstream_raw_patch_applies_clean": raw_check.returncode == 0,
        "upstream_raw_patch_exit_code": raw_check.returncode,
        "source_patch_translation_count": 4,
        "source_patch_sha256": hashlib.sha256(release_patch).hexdigest(),
        "source_patch_bytes": len(release_patch),
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
