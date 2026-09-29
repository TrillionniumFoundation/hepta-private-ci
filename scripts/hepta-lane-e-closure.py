#!/usr/bin/env python3
"""Compatibility entry point for the coherent Lane E verifier.

The wrapper intentionally re-exports the verifier surface consumed by repository
regression tests.  Keeping the compatibility module executable and importable
prevents workflow validation from silently exercising a different implementation.
"""

from __future__ import annotations

from hepta_lane_e_closure_v2 import Findings
from hepta_lane_e_closure_v2 import WORKFLOW_PATH
from hepta_lane_e_closure_v2 import main
from hepta_lane_e_closure_v2 import verify_workflow

__all__ = ["Findings", "WORKFLOW_PATH", "main", "verify_workflow"]


if __name__ == "__main__":
    raise SystemExit(main())
