"""Resolve versioned address packages without modifying frozen V7 or V8."""

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
QUALIFICATION = HERE.parents[1]
for root in (HERE, QUALIFICATION / "memory-cell-v7", QUALIFICATION / "memory-cell-v6"):
    sys.path.insert(0, str(root))
