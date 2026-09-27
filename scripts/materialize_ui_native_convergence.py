#!/usr/bin/env python3
"""Materialize the reviewed ui.native convergence patch.

The repository stores the large, reviewable source delta as a gzip-compressed,
base64-encoded unified patch.  This helper is deliberately small and strict:
it only runs on the dedicated integration branch, rejects path traversal and
Git metadata writes, verifies that the worktree is clean, and applies the patch
through ``git apply --index`` so the workflow can validate the exact staged
bytes before committing them.

The operation is idempotent.  If the complete patch is already present,
``git apply --reverse --check`` must prove that fact; a partial or drifting
application remains a hard failure.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

BRANCH = "work/ui-native-integration-convergence-20260927"
PATCH_PATH = Path(".github/materializers/ui-native-convergence.patch.gz.b64")
DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)


class MaterializationError(RuntimeError):
    """Raised when the immutable materialization contract is not satisfied."""


def git(root: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[bytes], operation: str) -> bytes:
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise MaterializationError(f"{operation} failed: {detail}")
    return result.stdout


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return Path(require_ok(result, "locate repository").decode().strip()).resolve()


def decode_patch(root: Path) -> bytes:
    path = root / PATCH_PATH
    if not path.is_file():
        raise MaterializationError(f"missing immutable patch payload: {PATCH_PATH}")
    encoded = b"".join(path.read_bytes().split())
    try:
        compressed = base64.b64decode(encoded, validate=True)
        patch = gzip.decompress(compressed)
        patch.decode("utf-8")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise MaterializationError(f"invalid patch payload: {exc}") from exc
    if not patch.startswith(b"diff --git ") or not patch.endswith(b"\n"):
        raise MaterializationError("decoded payload is not a complete git patch")
    return patch


def validate_paths(patch: bytes) -> set[str]:
    text = patch.decode("utf-8")
    pairs = DIFF_HEADER.findall(text)
    if not pairs:
        raise MaterializationError("patch contains no diff headers")
    paths: set[str] = set()
    for old_name, new_name in pairs:
        for name in (old_name, new_name):
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                raise MaterializationError(f"unsafe patch path: {name!r}")
            if pure.parts[0] == ".git":
                raise MaterializationError("patch may not modify Git metadata")
            paths.add(name)
    return paths


def current_branch(root: Path) -> str:
    return require_ok(
        git(root, "branch", "--show-current"), "read current branch"
    ).decode().strip()


def ensure_clean(root: Path) -> None:
    status = require_ok(
        git(root, "status", "--porcelain=v1", "--untracked-files=all"),
        "inspect worktree",
    ).decode()
    if status:
        raise MaterializationError(
            "refusing to materialize over a dirty worktree:\n" + status.rstrip()
        )


def staged_paths(root: Path) -> set[str]:
    output = require_ok(
        git(root, "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB"),
        "enumerate staged files",
    ).decode()
    return {line for line in output.splitlines() if line}


def materialize(root: Path, patch: bytes, declared_paths: set[str]) -> str:
    forward = git(root, "apply", "--check", "--whitespace=error-all", "-", input_bytes=patch)
    if forward.returncode == 0:
        require_ok(
            git(root, "apply", "--index", "--whitespace=error-all", "-", input_bytes=patch),
            "apply convergence patch",
        )
        staged = staged_paths(root)
        unexpected = staged - declared_paths
        if unexpected:
            raise MaterializationError(
                "git apply staged paths outside the patch headers: "
                + ", ".join(sorted(unexpected))
            )
        missing = declared_paths - staged
        if missing:
            raise MaterializationError(
                "patch headers were not fully materialized: " + ", ".join(sorted(missing))
            )
        return "applied"

    reverse = git(
        root,
        "apply",
        "--reverse",
        "--check",
        "--whitespace=error-all",
        "-",
        input_bytes=patch,
    )
    if reverse.returncode == 0:
        return "already-applied"

    forward_error = forward.stderr.decode("utf-8", errors="replace").strip()
    reverse_error = reverse.stderr.decode("utf-8", errors="replace").strip()
    raise MaterializationError(
        "patch is neither cleanly applicable nor completely present; baseline drift or "
        f"partial application detected\nforward: {forward_error}\nreverse: {reverse_error}"
    )


def main() -> int:
    try:
        root = repository_root()
        branch = current_branch(root)
        allow_other_branch = os.environ.get("HEPTA_UI_NATIVE_ALLOW_OTHER_BRANCH") == "1"
        if branch != BRANCH and not allow_other_branch:
            raise MaterializationError(
                f"expected branch {BRANCH!r}, found {branch!r}; set "
                "HEPTA_UI_NATIVE_ALLOW_OTHER_BRANCH=1 only in an isolated verification checkout"
            )
        ensure_clean(root)
        patch = decode_patch(root)
        paths = validate_paths(patch)
        digest = hashlib.sha256(patch).hexdigest()
        outcome = materialize(root, patch, paths)
        print(
            f"ui.native convergence patch {outcome}: sha256={digest} files={len(paths)}",
            flush=True,
        )
        return 0
    except MaterializationError as exc:
        print(f"materialization error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
