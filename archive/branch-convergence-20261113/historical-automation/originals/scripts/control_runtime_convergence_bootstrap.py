#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BODY = SCRIPTS / "control_runtime_convergence_body.py"

# Preserve the original exact-match source transformation as an immutable body,
# then apply the durability/execution wiring against the transformed tree.
runpy.run_path(str(BODY), run_name="__main__")
sys.path.insert(0, str(SCRIPTS))
from control_runtime_stage3_bootstrap import apply

apply()
BODY.unlink(missing_ok=True)
