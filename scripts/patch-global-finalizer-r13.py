#!/usr/bin/env python3
"""Finish the audited r13 repairs to the r7 global finalizer.

The dependency scanner is already cycle-aware on this controller head. This
script verifies that complete implementation and applies only the remaining
Lane F cleanup. Partial or contradictory states still fail closed.
"""
from __future__ import annotations

from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    cycle_safe_contract = (
        "def imported_workspace_crates_by_kind(",
        "def workspace_dependency_graph(",
        "def dependency_cycle_path(",
        "cycle = dependency_cycle_path(graph, package_name, dependency_name)",
        '"skippedCycles": skipped_cycles',
        '"skippedCycleCount": len(skipped_cycles)',
    )
    missing = [phrase for phrase in cycle_safe_contract if phrase not in text]
    if missing:
        raise SystemExit(
            "cycle-safe dependency repair is incomplete: " + ", ".join(missing)
        )

    old_lane_f = '''        for path in conflicts:
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
'''
    new_lane_f = '''        for path in conflicts:
            if (
                lane_f_owner_conflict
                and path == ".github/workflows/lane-f-bootstrap.yml"
            ):
                git("rm", "--", path)
                continue
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
'''
    old_count = text.count(old_lane_f)
    new_count = text.count(new_lane_f)
    if old_count == 1 and new_count == 0:
        text = text.replace(old_lane_f, new_lane_f, 1)
    elif old_count == 0 and new_count == 1:
        pass
    else:
        raise SystemExit(
            "Lane F cleanup state is ambiguous: "
            f"old={old_count} new={new_count}"
        )

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
