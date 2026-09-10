#!/usr/bin/env python3
"""Identity-binding wrapper for the deterministic r8 repair replay."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
R8_PATH = SCRIPT_DIR / "hepta-global-finalizer-r8.py"
SPEC = importlib.util.spec_from_file_location("hepta_global_finalizer_r8", R8_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load r8 executor from {R8_PATH}")
r8 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r8
SPEC.loader.exec_module(r8)

_original_write_json = r8.r7.write_json


def identity_bound_write_json(path: Path, value: Any) -> None:
    if (
        path.name == "PREPARE.json"
        and isinstance(value, dict)
        and isinstance(value.get("qualifiedSourceCommit"), str)
    ):
        value = dict(value)
        value["inputSourceCommit"] = value.get("sourceCommit")
        value["sourceCommit"] = value["qualifiedSourceCommit"]
    _original_write_json(path, value)


r8.r7.write_json = identity_bound_write_json

if __name__ == "__main__":
    raise SystemExit(r8.main())
