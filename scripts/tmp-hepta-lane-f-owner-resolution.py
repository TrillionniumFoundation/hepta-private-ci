#!/usr/bin/env python3
"""Apply the exact, bounded Lane F ownership rule to the r7 convergence executor."""

from pathlib import Path

PATH = Path("scripts/hepta-global-finalizer-r7.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"expected one replacement marker, found {count}: {old[:100]!r}"
        )
    text = text.replace(old, new, 1)


if "LANE_F_OWNER_CONFLICTS" not in text:
    marker = "\n\ndef merge_lane(lane: str, branch: str) -> dict[str, Any]:\n"
    lane_f_contract = """

LANE_F_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/hepta-lane-f-shadow-qualification.yml",
        ".github/workflows/lane-f-bootstrap.yml",
        "qualification/lane-f-shadow/src/lib.rs",
    }
)
"""
    replace_once(marker, lane_f_contract + marker)
    replace_once(
        "    lane_d_prior_owner_conflict = False\n",
        "    lane_d_prior_owner_conflict = False\n    lane_f_owner_conflict = False\n",
    )
    replace_once(
        "        lane_d_prior_owner_conflict = (\n"
        "            lane == \"D\"\n"
        "            and len(conflicts) == len(LANE_D_PRIOR_OWNER_CONFLICTS)\n"
        "            and frozenset(conflicts) == LANE_D_PRIOR_OWNER_CONFLICTS\n"
        "        )\n",
        "        lane_d_prior_owner_conflict = (\n"
        "            lane == \"D\"\n"
        "            and len(conflicts) == len(LANE_D_PRIOR_OWNER_CONFLICTS)\n"
        "            and frozenset(conflicts) == LANE_D_PRIOR_OWNER_CONFLICTS\n"
        "        )\n"
        "        lane_f_owner_conflict = (\n"
        "            lane == \"F\"\n"
        "            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)\n"
        "            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS\n"
        "        )\n",
    )
    replace_once(
        "            and not lane_d_prior_owner_conflict\n        ):\n",
        "            and not lane_d_prior_owner_conflict\n"
        "            and not lane_f_owner_conflict\n"
        "        ):\n",
    )
    replace_once(
        "        checkout_side = \"--theirs\" if lane_owner_conflict else \"--ours\"\n",
        "        checkout_side = (\n"
        "            \"--theirs\"\n"
        "            if lane_owner_conflict or lane_f_owner_conflict\n"
        "            else \"--ours\"\n"
        "        )\n",
    )
    replace_once(
        "        elif lane_d_prior_owner_conflict:\n"
        "            resolution_class = \"prior Lane A/C owner paths retained during Lane D merge\"\n"
        "        else:\n",
        "        elif lane_d_prior_owner_conflict:\n"
        "            resolution_class = \"prior Lane A/C owner paths retained during Lane D merge\"\n"
        "        elif lane_f_owner_conflict:\n"
        "            resolution_class = \"Lane F owner shadow qualification paths\"\n"
        "        else:\n",
    )
    replace_once(
        "            and not lane_d_prior_owner_conflict\n        ),\n",
        "            and not lane_d_prior_owner_conflict\n"
        "            and not lane_f_owner_conflict\n"
        "        ),\n",
    )
    replace_once(
        "        \"autoResolvedLaneDPriorOwnerOnly\": lane_d_prior_owner_conflict,\n",
        "        \"autoResolvedLaneDPriorOwnerOnly\": lane_d_prior_owner_conflict,\n"
        "        \"autoResolvedLaneFOwnerOnly\": lane_f_owner_conflict,\n",
    )
else:
    required = (
        '".github/workflows/hepta-lane-f-shadow-qualification.yml"',
        '".github/workflows/lane-f-bootstrap.yml"',
        '"qualification/lane-f-shadow/src/lib.rs"',
        '"autoResolvedLaneFOwnerOnly"',
    )
    missing = [fragment for fragment in required if fragment not in text]
    if missing:
        raise SystemExit(f"partial Lane F owner patch: {missing!r}")

PATH.write_text(text, encoding="utf-8")
