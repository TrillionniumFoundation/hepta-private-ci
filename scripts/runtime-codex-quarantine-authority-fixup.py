#!/usr/bin/env python3
"""Compatibility entrypoint for the corrected resolution-authority migration."""

from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).with_name("runtime-codex-quarantine-authority-v2.py")),
    run_name="__main__",
)
