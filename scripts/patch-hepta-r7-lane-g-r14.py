#!/usr/bin/env python3
"""Apply the exact Lane F/Lane G conflict-policy repair to the r7 finalizer.

The repair is intentionally one-shot and fail-closed. Lane F's transient bootstrap
publisher is deleted rather than inherited. Lane G's two known shared-file
conflicts retain the already-converged generated binding table and split test
harness; the native-binding generator then rebinds source blobs after all lanes
are present.
"""
from __future__ import annotations

from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} patch precondition drifted: old-count={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        '''LANE_F_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/hepta-lane-f-shadow-qualification.yml",
        ".github/workflows/lane-f-bootstrap.yml",
        "qualification/lane-f-shadow/src/lib.rs",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
''',
        '''LANE_F_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/hepta-lane-f-shadow-qualification.yml",
        ".github/workflows/lane-f-bootstrap.yml",
        "qualification/lane-f-shadow/src/lib.rs",
    }
)

LANE_G_PRIOR_OWNER_CONFLICTS = frozenset(
    {
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
''',
        "Lane G conflict set",
    )

    text = replace_exact(
        text,
        '''    lane_d_prior_owner_conflict = False
    lane_f_owner_conflict = False
    if not result.passed:
''',
        '''    lane_d_prior_owner_conflict = False
    lane_f_owner_conflict = False
    lane_g_prior_owner_conflict = False
    if not result.passed:
''',
        "Lane G conflict state",
    )

    text = replace_exact(
        text,
        '''        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        if (
''',
        '''        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        lane_g_prior_owner_conflict = (
            lane == "G"
            and len(conflicts) == len(LANE_G_PRIOR_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_G_PRIOR_OWNER_CONFLICTS
        )
        if (
''',
        "Lane G conflict recognition",
    )

    text = replace_exact(
        text,
        '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
        ):
''',
        '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
            and not lane_g_prior_owner_conflict
        ):
''',
        "Lane G conflict admission",
    )

    text = replace_exact(
        text,
        '''        for path in conflicts:
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
''',
        '''        for path in conflicts:
            if (
                lane_f_owner_conflict
                and path == ".github/workflows/lane-f-bootstrap.yml"
            ):
                git("rm", "--", path)
                continue
            git("checkout", checkout_side, "--", path)
            git("add", "--", path)
''',
        "Lane F bootstrap deletion",
    )

    text = replace_exact(
        text,
        '''        elif lane_f_owner_conflict:
            resolution_class = "Lane F owner shadow qualification paths"
        else:
''',
        '''        elif lane_f_owner_conflict:
            resolution_class = "Lane F owner shadow qualification paths"
        elif lane_g_prior_owner_conflict:
            resolution_class = "prior cumulative owner metadata retained during Lane G merge"
        else:
''',
        "Lane G resolution receipt",
    )

    text = replace_exact(
        text,
        '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
        ),
''',
        '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
            and not lane_g_prior_owner_conflict
        ),
''',
        "Lane G generated-only classification",
    )

    text = replace_exact(
        text,
        '''        "autoResolvedLaneDPriorOwnerOnly": lane_d_prior_owner_conflict,
        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "conflicts": conflicts,
''',
        '''        "autoResolvedLaneDPriorOwnerOnly": lane_d_prior_owner_conflict,
        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "autoResolvedLaneGPriorOwnerOnly": lane_g_prior_owner_conflict,
        "conflicts": conflicts,
''',
        "Lane G result binding",
    )

    required = (
        "LANE_G_PRIOR_OWNER_CONFLICTS",
        "lane_g_prior_owner_conflict",
        'path == ".github/workflows/lane-f-bootstrap.yml"',
        'git("rm", "--", path)',
        '"autoResolvedLaneGPriorOwnerOnly"',
        "def workspace_dependency_graph(",
        "def dependency_cycle_path(",
        '"skippedCycleCount"',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"patched finalizer is missing required phrase: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
