#!/usr/bin/env bash
set -euo pipefail

EXPECTED_REPO="TrillionniumFoundation/hepta-private-ci"
CONTROLLER_BRANCH="ops/hepta-global-gap-closure-controller-20260910-r1"
WORKFLOW_MODE=false
if [[ "${1:-}" == "--workflow-mode" ]]; then
  WORKFLOW_MODE=true
fi

root="$(git rev-parse --show-toplevel)"
cd "${root}"
remote_url="$(git remote get-url origin)"
case "${remote_url}" in
  *"${EXPECTED_REPO}"*) ;;
  *) echo "unexpected origin: ${remote_url}" >&2; exit 2 ;;
esac

if [[ "${WORKFLOW_MODE}" != true ]]; then
  git fetch --prune origin
  git checkout "${CONTROLLER_BRANCH}"
  git pull --ff-only origin "${CONTROLLER_BRANCH}"
fi

python3 - <<'PY'
from pathlib import Path

path = Path("scripts/hepta-global-finalizer-r7.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, marker: str) -> None:
    global text
    count = text.count(old)
    if count == 1:
        text = text.replace(old, new, 1)
        return
    if count == 0 and marker in text:
        return
    raise SystemExit(
        f"r7 remediation anchor drift for {marker!r}: observed old-count={count}"
    )


constant_anchor = "\n\n\ndef merge_lane(lane: str, branch: str) -> dict[str, Any]:\n"
constant_replacement = '''

LANE_F_OWNER_CONFLICTS = frozenset(
    {
        ".github/workflows/hepta-lane-f-shadow-qualification.yml",
        ".github/workflows/lane-f-bootstrap.yml",
        "qualification/lane-f-shadow/src/lib.rs",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
'''
replace_once(constant_anchor, constant_replacement, "LANE_F_OWNER_CONFLICTS")

replace_once(
    "    lane_d_prior_owner_conflict = False\n",
    "    lane_d_prior_owner_conflict = False\n    lane_f_owner_conflict = False\n",
    "lane_f_owner_conflict = False",
)

old = '''        lane_d_prior_owner_conflict = (
            lane == "D"
            and len(conflicts) == len(LANE_D_PRIOR_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_D_PRIOR_OWNER_CONFLICTS
        )
        if (
'''
new = '''        lane_d_prior_owner_conflict = (
            lane == "D"
            and len(conflicts) == len(LANE_D_PRIOR_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_D_PRIOR_OWNER_CONFLICTS
        )
        lane_f_owner_conflict = (
            lane == "F"
            and len(conflicts) == len(LANE_F_OWNER_CONFLICTS)
            and frozenset(conflicts) == LANE_F_OWNER_CONFLICTS
        )
        if (
'''
replace_once(old, new, "lane_f_owner_conflict = (")

replace_once(
    '''            and not lane_d_prior_owner_conflict
        ):
''',
    '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
        ):
''',
    "and not lane_f_owner_conflict",
)

replace_once(
    '''        checkout_side = "--theirs" if lane_owner_conflict else "--ours"
''',
    '''        checkout_side = (
            "--theirs" if lane_owner_conflict or lane_f_owner_conflict else "--ours"
        )
''',
    "lane_owner_conflict or lane_f_owner_conflict",
)

old = '''        elif lane_d_prior_owner_conflict:
            resolution_class = "prior Lane A/C owner paths retained during Lane D merge"
        else:
'''
new = '''        elif lane_d_prior_owner_conflict:
            resolution_class = "prior Lane A/C owner paths retained during Lane D merge"
        elif lane_f_owner_conflict:
            resolution_class = "latest Lane F owner shadow qualification bundle"
        else:
'''
replace_once(old, new, "latest Lane F owner shadow qualification bundle")

replace_once(
    '''            and not lane_d_prior_owner_conflict
        ),
''',
    '''            and not lane_d_prior_owner_conflict
            and not lane_f_owner_conflict
        ),
''',
    "and not lane_f_owner_conflict",
)

replace_once(
    '''        "autoResolvedLaneDPriorOwnerOnly": lane_d_prior_owner_conflict,
        "conflicts": conflicts,
''',
    '''        "autoResolvedLaneDPriorOwnerOnly": lane_d_prior_owner_conflict,
        "autoResolvedLaneFOwnerOnly": lane_f_owner_conflict,
        "conflicts": conflicts,
''',
    "autoResolvedLaneFOwnerOnly",
)

path.write_text(text, encoding="utf-8")
PY

uv run --frozen --project scripts ruff format scripts/hepta-global-finalizer-r7.py
uv run --frozen --project scripts ruff format --check scripts/hepta-global-finalizer-r7.py
python3 -m py_compile scripts/hepta-global-finalizer-r7.py
git diff --check

git config user.name "Hepta Blocker Remediator"
git config user.email "noreply@openai.com"
git add scripts/hepta-global-finalizer-r7.py
if ! git diff --cached --quiet; then
  git commit --signoff -m "fix(hepta): select exact Lane F owner bundle during convergence"
  git push origin "HEAD:refs/heads/${CONTROLLER_BRANCH}"
fi

printf '%s\n' \
  "Applied exact Lane-F owner conflict policy; all unrecognized conflicts remain fail-closed."
