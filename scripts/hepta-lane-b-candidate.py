#!/usr/bin/env python3
"""Compatibility entrypoint delegating to the single Lane B verifier."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
args = sys.argv[1:] or ["verify"]
raise SystemExit(
    subprocess.call(
        [sys.executable, str(ROOT / "scripts/hepta-lane-b-truth.py"), *args],
        cwd=ROOT,
    )
)
