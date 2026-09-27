#!/usr/bin/env python3
"""Apply the reviewed strict prompt.registry V4 storage patch idempotently."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patches/prompt-registry-schema-v4.patch"
PATCH_SHA256 = "6eec2f2c5ccc186c34f0c9d11a4b02fca9065f42b0d6ef5cb0aeb89c3876a3db"


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> None:
    patch = PATCH.read_bytes()
    actual = hashlib.sha256(patch).hexdigest()
    if actual != PATCH_SHA256:
        raise SystemExit(
            f"prompt.registry V4 patch digest mismatch: {actual} != {PATCH_SHA256}"
        )

    patch_path = str(PATCH)
    if run("git", "apply", "--reverse", "--check", patch_path).returncode == 0:
        return

    check = run("git", "apply", "--check", patch_path)
    if check.returncode != 0:
        raise SystemExit(
            "reviewed prompt.registry V4 patch no longer applies:\n"
            + check.stderr.decode("utf-8", errors="replace")
        )

    applied = run("git", "apply", patch_path)
    if applied.returncode != 0:
        raise SystemExit(applied.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
