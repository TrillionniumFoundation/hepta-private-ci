#!/usr/bin/env python3
"""Run every read-only platform.types generated-artifact verifier."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    (
        "public API inventory",
        (sys.executable, "scripts/platform_types_public_api.py"),
    ),
    (
        "implementation map",
        (sys.executable, "scripts/platform_types_implementation_map.py"),
    ),
    (
        "compatibility matrix",
        (sys.executable, "scripts/check_platform_types_compatibility_matrix.py"),
    ),
    (
        "current truth matrix",
        (sys.executable, "scripts/platform_types_truth_matrix.py", "--check"),
    ),
)


def main() -> int:
    for label, command in CHECKS:
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            print(
                f"platform.types generated artifacts failed at {label}",
                file=sys.stderr,
            )
            return completed.returncode
    print("platform.types generated artifacts: all read-only checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
