#!/usr/bin/env python3
"""Run the r6 governance controller after same-job exact-SHA qualification."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_gap_convergence_controller_20260909_r6.py")
SPEC = importlib.util.spec_from_file_location("hepta_r6_controller", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"unable to load controller: {SCRIPT}")
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)

qualified_head = os.environ.get("QUALIFIED_HEAD", "").strip()
if len(qualified_head) != 40:
    raise SystemExit("QUALIFIED_HEAD must be an exact 40-character commit SHA")

original_verify_candidate = controller.verify_candidate


def verify_exact_qualified_candidate(pr: dict) -> str:
    observed = original_verify_candidate(pr)
    if observed != qualified_head:
        raise controller.ControllerError(
            f"qualified/head race: same-job qualified {qualified_head}, current PR head {observed}"
        )
    return observed


controller.verify_candidate = verify_exact_qualified_candidate
controller.successful_r5_attempt = lambda: (
    True,
    f"same-job native MSVC qualification on exact candidate {qualified_head}",
)
controller.main()
