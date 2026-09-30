#!/usr/bin/env python3
"""Bind the retained six-subject aggregate validator to the sole workflow."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hepta_ui_native_evidence as evidence

CURRENT_WORKFLOW = ".github/workflows/ui-native-qualification.yml"
COMPILE_NEGATIVE = "compile_negative"

evidence.WORKFLOW = CURRENT_WORKFLOW
if COMPILE_NEGATIVE not in evidence.REQUIRED:
    evidence.REQUIRED = (*evidence.REQUIRED, COMPILE_NEGATIVE)

import hepta_ui_native_aggregate as aggregate

aggregate.evidence.WORKFLOW = CURRENT_WORKFLOW
aggregate.evidence.REQUIRED = evidence.REQUIRED

if __name__ == "__main__":
    raise SystemExit(aggregate.main())
