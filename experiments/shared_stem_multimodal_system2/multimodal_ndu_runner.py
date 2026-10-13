"""Stable public name for the multimodal/NDU experiment runner.

The implementation is kept in :mod:`runner` so the generic CLI and tests have
one owner.  This module is the name used by the shared Stem experiment suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from experiments.shared_stem_multimodal_system2.runner import *  # noqa: F401,F403
else:
    from .runner import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
