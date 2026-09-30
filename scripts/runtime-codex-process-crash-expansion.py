#!/usr/bin/env python3
"""Compatibility entrypoint for corrected process-crash expansion."""

from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).with_name("runtime-codex-process-crash-expansion-v2.py")),
    run_name="__main__",
)
