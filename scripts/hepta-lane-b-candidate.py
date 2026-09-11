#!/usr/bin/env python3
"""Compatibility entrypoint for the unified Lane B verifier.

The former candidate-specific validator duplicated the truth validator and
drifted across schema versions. Keep one implementation and route legacy calls
to it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    script = Path(__file__).with_name("hepta-lane-b-truth.py")
    process = subprocess.run([sys.executable, str(script), *sys.argv[1:]], check=False)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
