#!/usr/bin/env python3
"""Race-free, exact-status-bound wrapper for the r10 fixed-point sealer."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

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

R8_STATUS_PATH = os.environ.get(
    "HEPTA_R8_STATUS_PATH",
    "qualification/global-gap-closure-final-r8/STATUS.json",
)
R9_STATUS_PATH = os.environ.get(
    "HEPTA_R9_STATUS_PATH",
    "qualification/global-gap-closure-final-r9/STATUS.json",
)
R8_TARGET = "integration/hepta-all-gap-closure-20260910-r8"
R9_TARGET = "integration/hepta-all-gap-closure-20260910-r9"


def read_exact_status(
    ref: str,
    path: str,
    expected_target: str,
) -> tuple[str, dict[str, Any]]:
    raw = r10.git("show", f"{ref}:{path}", check=False)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"no parseable bound status at {ref}:{path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"bound status at {ref}:{path} is not an object")
    if value.get("targetBranch") != expected_target:
        raise RuntimeError(
            f"status target mismatch at {ref}:{path}: "
            f"{value.get('targetBranch')} != {expected_target}"
        )
    if not r10.status_passed(value):
        raise RuntimeError(f"status is not internally complete at {ref}:{path}")
    if value.get("externalAuthorityGatesRetained") is not True:
        raise RuntimeError(f"external authority gates not retained at {ref}:{path}")
    if value.get("allGapsClosed") is not False:
        raise RuntimeError(f"invalid all-gaps claim at {ref}:{path}")
    r10.qualified_source(value)
    return path, value


def read_bound_status(ref: str) -> tuple[str, dict[str, Any]]:
    if ref == r10.R8_REF:
        return read_exact_status(ref, R8_STATUS_PATH, R8_TARGET)
    if ref == r10.R9_REF:
        return read_exact_status(ref, R9_STATUS_PATH, R9_TARGET)
    raise RuntimeError(f"unexpected fixed-point input ref: {ref}")


def wait_for_bound_statuses() -> None:
    for _ in range(2160):
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
            read_bound_status(r10.R8_REF)
            read_bound_status(r10.R9_REF)
        except RuntimeError:
            time.sleep(10)
            continue
        return
    raise RuntimeError("r8/r9 did not expose exact passing bound statuses")


r10.read_status = read_bound_status
r10.wait_for_refs = wait_for_bound_statuses

if __name__ == "__main__":
    try:
        raise SystemExit(r10.main())
    except Exception as error:
        print(f"HEPTA_FIXED_POINT_SEALER_R11_ERROR: {error}", file=sys.stderr)
        raise
