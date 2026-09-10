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

LANE_C_SPLIT_TEST_HARNESS_CONFLICT = (
    "qualification/module-execution-dossiers/test_implementation_contracts.py"
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
'''
replace_once(
    constant_anchor,
    constant_replacement,
    "LANE_C_SPLIT_TEST_HARNESS_CONFLICT",
)

replace_once(
    "    prior_lane_owner_conflict = False\n",
    "    prior_lane_owner_conflict = False\n    split_test_harness_conflict = False\n",
    "split_test_harness_conflict = False",
)

old = '''        prior_lane_owner_conflict = (
            lane == "B"
            and len(conflicts) == len(LANE_B_PRIOR_LANE_A_CONFLICTS)
            and frozenset(conflicts) == LANE_B_PRIOR_LANE_A_CONFLICTS
        )
        if (
'''
new = '''        prior_lane_owner_conflict = (
            lane == "B"
            and len(conflicts) == len(LANE_B_PRIOR_LANE_A_CONFLICTS)
            and frozenset(conflicts) == LANE_B_PRIOR_LANE_A_CONFLICTS
        )
        split_test_harness_conflict = lane == "C" and conflicts == [
            LANE_C_SPLIT_TEST_HARNESS_CONFLICT
        ]
        if (
'''
replace_once(old, new, "split_test_harness_conflict = lane == \"C\"")

replace_once(
    '''            and not prior_lane_owner_conflict
        ):
''',
    '''            and not prior_lane_owner_conflict
            and not split_test_harness_conflict
        ):
''',
    "and not split_test_harness_conflict",
)

old = '''        elif prior_lane_owner_conflict:
            resolution_class = "prior lane-A owner paths retained during lane-B merge"
        else:
'''
new = '''        elif prior_lane_owner_conflict:
            resolution_class = "prior lane-A owner paths retained during lane-B merge"
        elif split_test_harness_conflict:
            resolution_class = "split implementation-contract test harness"
        else:
'''
replace_once(old, new, "split implementation-contract test harness")

replace_once(
    '''            auto_resolved and not lane_owner_conflict and not prior_lane_owner_conflict
        ),
''',
    '''            auto_resolved
            and not lane_owner_conflict
            and not prior_lane_owner_conflict
            and not split_test_harness_conflict
        ),
''',
    "and not split_test_harness_conflict",
)

replace_once(
    '''        "autoResolvedPriorLaneOwnerOnly": prior_lane_owner_conflict,
        "conflicts": conflicts,
''',
    '''        "autoResolvedPriorLaneOwnerOnly": prior_lane_owner_conflict,
        "autoResolvedSplitTestHarnessOnly": split_test_harness_conflict,
        "conflicts": conflicts,
''',
    "autoResolvedSplitTestHarnessOnly",
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
  git commit --signoff -m "fix(hepta): preserve split contract tests during Lane C convergence"
  git push origin "HEAD:refs/heads/${CONTROLLER_BRANCH}"
fi

printf '%s\n' \
  "Applied exact Lane-C split-test conflict policy; all unrecognized conflicts remain fail-closed."
