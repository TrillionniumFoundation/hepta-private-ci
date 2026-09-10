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


old = '''def generated_conflicts_only(paths: Sequence[str]) -> bool:
    return bool(paths) and all(
        any(pattern.match(path) for pattern in GENERATED_CONFLICTS) for path in paths
    )


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
'''
new = '''def generated_conflicts_only(paths: Sequence[str]) -> bool:
    return bool(paths) and all(
        any(pattern.match(path) for pattern in GENERATED_CONFLICTS) for path in paths
    )


LANE_B_PRIOR_LANE_A_CONFLICTS = frozenset(
    {
        ".github/workflows/lane-a-foundation.yml",
        "codex-rs/hepta-authbus/src/lib.rs",
        "codex-rs/hepta-authbus/src/lib_tests.rs",
        "codex-rs/hepta-operations/src/ledger.rs",
        "codex-rs/hepta-operations/src/ledger_tests.rs",
        "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json",
        "docs/lane-a-foundation/README.md",
        "docs/lane-a-foundation/STATUS_MODEL.md",
        "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/kernel.operations/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
        "docs/lane-a-foundation/platform.wire/WIRE_V1.md",
        "docs/lane-a-foundation/secrets.heptabao/CURRENT_IMPLEMENTATION.md",
        "qualification/module-execution-dossiers/NATIVE_BINDINGS.json",
        "qualification/module-execution-dossiers/test_implementation_contracts.py",
        "qualification/module-execution-dossiers/test_lane_a_foundation.py",
        "scripts/verify_lane_a_foundation.py",
    }
)


def merge_lane(lane: str, branch: str) -> dict[str, Any]:
'''
replace_once(old, new, "LANE_B_PRIOR_LANE_A_CONFLICTS")

replace_once(
    "    lane_owner_conflict = False\n",
    "    lane_owner_conflict = False\n    prior_lane_owner_conflict = False\n",
    "prior_lane_owner_conflict = False",
)

old = '''        lane_owner_conflict = lane == "E" and conflicts == ["docs/lane-e/README.md"]
        if not generated_conflicts_only(conflicts) and not lane_owner_conflict:
'''
new = '''        lane_owner_conflict = lane == "E" and conflicts == ["docs/lane-e/README.md"]
        prior_lane_owner_conflict = (
            lane == "B"
            and len(conflicts) == len(LANE_B_PRIOR_LANE_A_CONFLICTS)
            and frozenset(conflicts) == LANE_B_PRIOR_LANE_A_CONFLICTS
        )
        if (
            not generated_conflicts_only(conflicts)
            and not lane_owner_conflict
            and not prior_lane_owner_conflict
        ):
'''
replace_once(old, new, "frozenset(conflicts) == LANE_B_PRIOR_LANE_A_CONFLICTS")

old = '''        resolution_class = (
            "lane-E owner documentation"
            if lane_owner_conflict
            else "generated convergence metadata"
        )
'''
new = '''        if lane_owner_conflict:
            resolution_class = "lane-E owner documentation"
        elif prior_lane_owner_conflict:
            resolution_class = "prior lane-A owner paths retained during lane-B merge"
        else:
            resolution_class = "generated convergence metadata"
'''
replace_once(old, new, "prior lane-A owner paths retained during lane-B merge")

old = '''        "autoResolvedGeneratedOnly": auto_resolved and not lane_owner_conflict,
        "autoResolvedLaneOwnerOnly": lane_owner_conflict,
        "conflicts": conflicts,
'''
new = '''        "autoResolvedGeneratedOnly": (
            auto_resolved and not lane_owner_conflict and not prior_lane_owner_conflict
        ),
        "autoResolvedLaneOwnerOnly": lane_owner_conflict,
        "autoResolvedPriorLaneOwnerOnly": prior_lane_owner_conflict,
        "conflicts": conflicts,
'''
replace_once(old, new, "autoResolvedPriorLaneOwnerOnly")

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
  git commit --signoff -m "fix(hepta): retain exact prior-lane owner paths during Lane B merge"
  git push origin "HEAD:refs/heads/${CONTROLLER_BRANCH}"
fi

printf '%s\n' \
  "Applied exact Lane-B/prior-Lane-A conflict policy; all unrecognized conflict sets remain fail-closed."
