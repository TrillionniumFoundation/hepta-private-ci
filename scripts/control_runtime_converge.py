#!/usr/bin/env python3
"""Deterministic branch-local convergence driver for control.runtime.

The driver intentionally starts as a no-op harness. Subsequent commits extend
its exact, assertion-guarded source transformations; --verify always fails if
an expected source anchor has drifted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    ROOT / "codex-rs/hepta-control-plane/src/planner.rs",
    ROOT / "codex-rs/hepta-control-plane/src/planner_context.rs",
    ROOT / "codex-rs/hepta-agentd/src/cognitive_context.rs",
    ROOT / "docs/modules/control.runtime/IMPLEMENTATION_MAP.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply == args.verify:
        parser.error("choose exactly one of --apply or --verify")
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        raise SystemExit("missing required paths: " + ", ".join(missing))
    print("control.runtime convergence harness ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
