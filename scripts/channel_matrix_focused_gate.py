#!/usr/bin/env python3
"""Run the complete channel.matrix native and repository regression gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = ROOT / "codex-rs"
PACKAGES = (
    "codex-hepta-matrix-protocol",
    "codex-hepta-matrix-store",
    "codex-hepta-matrix-sdk",
    "codex-hepta-matrixd",
)
RUST_COMMAND = [
    "just",
    "test",
    "--locked",
    *[item for package in PACKAGES for item in ("-p", package)],
]
REPOSITORY_COMMAND = [
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-s",
    "../scripts/tests",
    "-p",
    "test_channel_matrix*.py",
    "-v",
]


def execute(arguments: Sequence[str]) -> int:
    try:
        return subprocess.run(
            list(arguments),
            cwd=CODEX_ROOT,
            check=False,
        ).returncode
    except OSError as exc:
        print(
            f"channel.matrix focused gate could not launch {arguments[0]}: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return 127


def main() -> int:
    # Execute both suites even when one fails so the retained command log
    # contains the complete repository-controlled diagnosis for this exact SHA.
    rust_status = execute(RUST_COMMAND)
    repository_status = execute(REPOSITORY_COMMAND)
    return 0 if rust_status == 0 and repository_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
