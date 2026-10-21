#!/usr/bin/env python3
"""Fail-closed hosted Linux CI disk admission for exact-source native impact tests.

Deletes ONLY literal, unused preinstalled SDK directories. Never deletes Git,
Cargo, Bazel, V8, checkout, or test artifacts. Writes a machine-readable receipt
outside the source tree and requires sufficient free disk before expensive work.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# This job compiles Rust on Ubuntu, not Android, .NET, Haskell or PowerShell.
# No directory or removal target is supplied by a PR author through CLI/env.
UNUSED_HOSTED_SDK_ROOTS = (
    Path("/usr/local/lib/android"),
    Path("/usr/share/dotnet"),
    Path("/opt/ghc"),
    Path("/usr/local/.ghcup"),
    Path("/usr/local/share/powershell"),
)
MINIMUM_FREE_BYTES = 12 * 1024**3


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def safe_sdk_directory(root: Path) -> bool:
    """Return False for an absent root; reject symlinks and unexpected types."""
    for candidate in (root, *root.parents):
        if candidate == Path("/"):
            break
        if candidate.is_symlink():
            raise RuntimeError(f"refusing symlink SDK path: {candidate}")
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"refusing non-directory SDK path: {root}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") != "true" or platform.system() != "Linux":
        parser.error("capacity reclamation is restricted to hosted GitHub Linux CI")
    source_sha = os.environ.get("SOURCE_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        parser.error("SOURCE_SHA must be a bound exact Git SHA")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    receipt = args.receipt.absolute()
    if not receipt.is_absolute() or receipt.is_relative_to(workspace):
        parser.error("receipt must be an absolute path outside the checked out source")
    tested_sha = run("git", "-C", str(workspace), "rev-parse", "HEAD").stdout.strip()
    if tested_sha != source_sha:
        parser.error("checked-out commit differs from the bound source SHA")

    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": source_sha,
        "tested_sha": tested_sha,
        "workspace": str(workspace),
        "minimum_free_bytes": MINIMUM_FREE_BYTES,
        "free_before_bytes": shutil.disk_usage(workspace).free,
        "removed_sdk_roots": [],
        "status": "running",
    }
    try:
        removed = []
        for root in UNUSED_HOSTED_SDK_ROOTS:
            if not safe_sdk_directory(root):
                continue
            disk_bytes = int(run("sudo", "du", "-sB1", "--", str(root)).stdout.split()[0])
            run("sudo", "rm", "-rf", "--one-file-system", "--", str(root))
            if root.exists() or root.is_symlink():
                raise RuntimeError(f"SDK root remains after cleanup: {root}")
            removed.append({"path": str(root), "du_bytes": disk_bytes})
        run("sudo", "apt-get", "clean")
        free_after = shutil.disk_usage(workspace).free
        evidence.update(
            removed_sdk_roots=removed,
            free_after_bytes=free_after,
            released_bytes=free_after - int(evidence["free_before_bytes"]),
        )
        if free_after < MINIMUM_FREE_BYTES:
            raise RuntimeError(
                f"insufficient native CI disk: {free_after} bytes free; "
                f"minimum {MINIMUM_FREE_BYTES}"
            )
        evidence["status"] = "passed"
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        evidence["status"] = "failed"
        evidence["error"] = str(error)
        raise
    finally:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
