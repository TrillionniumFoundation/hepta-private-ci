"""Locate frozen sibling research packages without shadowing v4 entry points."""

from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]
for name in (
    "memory-cell-research",
    "memory-cell-v2",
    "memory-cell-v3",
    "memory-cell-v4",
):
    path = str(PACKAGE.parent / name)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
