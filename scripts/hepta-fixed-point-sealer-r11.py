#!/usr/bin/env python3
"""Race-free wrapper for the r10 fixed-point sealer."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
R10_PATH = SCRIPT_DIR / "hepta-fixed-point-sealer-r10.py"
SPEC = importlib.util.spec_from_file_location("hepta_fixed_point_sealer_r10", R10_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load r10 sealer from {R10_PATH}")
r10 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r10
SPEC.loader.exec_module(r10)

r10.TARGET = os.environ.get(
    "HEPTA_SEALED_TARGET",
    "integration/hepta-all-gap-closure-20260910-sealed-r11",
)
r10.OUT = r10.ROOT / "qualification" / "global-gap-closure-seal-r11"


def wait_for_bound_statuses() -> None:
    for _ in range(720):
        r10.git(
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            check=False,
        )
        if not (r10.ref_exists(r10.R8_REF) and r10.ref_exists(r10.R9_REF)):
            time.sleep(10)
            continue
        try:
            r10.read_status(r10.R8_REF)
            r10.read_status(r10.R9_REF)
        except RuntimeError:
            time.sleep(10)
            continue
        return
    raise RuntimeError("r8/r9 refs did not both expose bound qualification status")


r10.wait_for_refs = wait_for_bound_statuses

if __name__ == "__main__":
    try:
        raise SystemExit(r10.main())
    except Exception as error:
        print(f"HEPTA_FIXED_POINT_SEALER_R11_ERROR: {error}", file=sys.stderr)
        raise
