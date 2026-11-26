#!/usr/bin/env python3
"""Free unused hosted SDKs before exact-revision reverse-consumer Rust CI.

This does not prune Cargo caches or alter the checkout. Never use it on a
self-hosted runner: shared machines and mounted tooling are outside its scope.
Every path removed is a hard-coded optional GitHub Ubuntu image SDK, and the
job still fails if it cannot provide its minimum headroom.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

GIB = 1024 ** 3
# Optional for native Rust reverse-consumer tests on Linux; checked in order.
OPTIONAL_HOSTED_SDKS = (
    Path("/usr/local/lib/android"),
    Path("/opt/ghc"),
    Path("/usr/share/dotnet"),
)


def eligible(target: Path, *, allowlist: tuple[Path, ...], workspace: Path) -> bool:
    """Prevent symlinks, mounts, checkout deletion and arbitrary path injection."""
    if target not in allowlist or not target.is_absolute() or target == Path("/"):
        return False
    if not target.is_dir() or target.is_mount():
        return False
    if target == workspace or target in workspace.parents or workspace in target.parents:
        return False
    # Check every ancestor rather than resolve the path and risk a symlink hop.
    if any(part.is_symlink() for part in (target, *target.parents)):
        return False
    return True


def require_hosted_linux(environment: dict[str, str]) -> None:
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("RUNNER_OS") != "Linux"
        or environment.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise RuntimeError("disk reclaim is allowed only on an ephemeral GitHub-hosted Linux runner")


def apply_reclaim(
    workspace: Path,
    *,
    minimum_bytes: int,
    apply: bool,
    allowlist: tuple[Path, ...] = OPTIONAL_HOSTED_SDKS,
) -> dict[str, object]:
    before = shutil.disk_usage(workspace).free
    removed: list[str] = []
    skipped: list[str] = []
    for target in allowlist:
        if shutil.disk_usage(workspace).free >= minimum_bytes:
            break
        if not eligible(target, allowlist=allowlist, workspace=workspace):
            skipped.append(str(target))
            continue
        if apply:
            subprocess.run(["sudo", "rm", "-rf", "--", str(target)], check=True)
        removed.append(str(target))
    after = shutil.disk_usage(workspace).free
    return {
        "before_free_bytes": before,
        "after_free_bytes": after,
        "target_free_bytes": minimum_bytes,
        "apply": apply,
        "sdk_paths_reclaimed_or_planned": removed,
        "sdk_paths_skipped": skipped,
        "sufficient": after >= minimum_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually reclaim eligible SDKs")
    parser.add_argument("--min-free-gib", type=int, default=20)
    args = parser.parse_args()
    if not 8 <= args.min_free_gib <= 80:
        parser.error("--min-free-gib must be in 8..80")
    require_hosted_linux(os.environ)
    workspace_raw = os.environ.get("GITHUB_WORKSPACE", "")
    if not workspace_raw or not Path(workspace_raw).is_absolute():
        raise RuntimeError("GITHUB_WORKSPACE must identify an absolute checkout")
    workspace = Path(workspace_raw)
    result = apply_reclaim(workspace, minimum_bytes=args.min_free_gib * GIB, apply=args.apply)
    print(json.dumps(result, sort_keys=True), flush=True)
    if args.apply and not result["sufficient"]:
        print("::error::Not enough runner disk for exhaustive native reverse consumers", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1) from error
