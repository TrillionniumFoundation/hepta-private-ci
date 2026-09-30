#!/usr/bin/env python3
"""Compatibility entry point for the coherent Lane E verifier."""

from __future__ import annotations

from hepta_lane_e_closure_v2 import Findings
from hepta_lane_e_closure_v2 import WORKFLOW_PATH
from hepta_lane_e_closure_v2 import main
from hepta_lane_e_closure_v2 import verify_workflows as verify_workflow


if __name__ == "__main__":
    raise SystemExit(main())
