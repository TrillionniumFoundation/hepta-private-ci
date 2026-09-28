#!/usr/bin/env python3
"""Prepare isolated, pinned archive qualification dependencies outside the checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    temporary = Path(os.environ["RUNNER_TEMP"])
    if not temporary.is_absolute() or not temporary.is_dir():
        raise SystemExit("RUNNER_TEMP must be an existing absolute directory")
    temporary = temporary.resolve(strict=True)
    if temporary.is_relative_to(root):
        raise SystemExit("archive environment must remain outside source")
    environment = temporary / "cognitive-archive-venv"
    environment.mkdir(mode=0o700, exist_ok=False)
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, timeout=120)
    python = environment / "bin/python"
    requirements = Path(__file__).with_name("archive-requirements.txt")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                    "--only-binary=:all:", "--requirement", str(requirements)],
                   check=True, timeout=300)
    subprocess.run([str(python), "-m", "pip", "check"], check=True, timeout=30)
    result = subprocess.run([str(python), "-m", "pip", "freeze"],
                            check=True, capture_output=True, text=True, timeout=30)
    print(json.dumps({"schema": "hepta.cognitive.archive-dependencies.v1",
                      "python": str(python), "packages": result.stdout.splitlines(),
                      "source_changed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
