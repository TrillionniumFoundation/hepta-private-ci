#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
controller_branch="ops/final-main-convergence-20260908"
candidate_branch="candidate/final-main-v6-20260908"
work_branch="hepta-final-source-v6"
report_dir="convergence"
evidence="$RUNNER_TEMP/hepta-materialize-v6"
patcher="$RUNNER_TEMP/fix_http_tls_classification.py"
mkdir -p "$evidence"
exec > >(tee "$evidence/materialize-v6.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"
cp .github/scripts/fix_http_tls_classification.py "$patcher"

git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune --force
git switch --force-create "$work_branch" origin/main
git reset --hard origin/main
git clean -ffdx
mkdir -p .github/scripts "$report_dir"
cp "$patcher" .github/scripts/fix_http_tls_classification.py

resolve_conflicts() {
  local preference="$1"
  mapfile -d '' conflicts < <(git diff --name-only --diff-filter=U -z)
  for path in "${conflicts[@]}"; do
    local stage=2
    [[ "$preference" == theirs ]] && stage=3
    if git ls-files -u -- "$path" | awk -v stage="$stage" '$3 == stage {found=1} END {exit !found}'; then
      git checkout --"$preference" -- "$path"
      git add -- "$path"
    else
      git rm -f --ignore-unmatch -- "$path"
    fi
  done
  if git diff --name-only --diff-filter=U | grep -q .; then
    echo "unresolved merge conflicts:" >&2
    git diff --name-only --diff-filter=U >&2
    return 1
  fi
}

merge_normal() {
  local ref="$1" preference="$2" label="$3"
  if ! git show-ref --verify --quiet "refs/remotes/$ref"; then
    printf '%s\tmissing\n' "$ref" >> "$report_dir/canonical-merges-v6.tsv"
    return 0
  fi
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$ref" >> "$report_dir/canonical-merges-v6.tsv"
    return 0
  fi
  echo "Normal merge: $ref; conflict preference=$preference"
  set +e
  git merge --no-ff --no-edit -X "$preference" "$ref" -m "merge(convergence-v6): $label"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    resolve_conflicts "$preference"
    git commit -s --no-edit
  fi
  printf '%s\tnormal-merge\t%s\n' "$ref" "$preference" >> "$report_dir/canonical-merges-v6.tsv"
}

: > "$report_dir/canonical-merges-v6.tsv"
primary="origin/codex/hepta-w0-seven-lanes-handoff-20260908"
git show-ref --verify --quiet "refs/remotes/$primary" || {
  echo "required W0 handoff is missing: $primary" >&2
  exit 10
}
merge_normal "$primary" theirs "canonical W0 seven-lane handoff"
merge_normal "origin/codex/hepta-bao-connect-20260908" ours "HeptaBao final-use boundary"
merge_normal "origin/reviewer/ci-governance-simplification-20260908" theirs "retire one-shot CI governance"
for ref in \
  "origin/codex/hepta-final-gap-closure-r3-20260908" \
  "origin/codex/hepta-final-gap-closure-r2-20260908" \
  "origin/integration/hepta-w0-internal-closure-20260908"; do
  merge_normal "$ref" ours "supplement ${ref#origin/}"
done

# This patcher runs the complete codex-http-client library tests and keeps only
# a source-chain-only classifier change that closes the six reproduced TLS
# failures without inspecting the outer reqwest value or its URL.
export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_INCREMENTAL=0
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_TEST_DEBUG=0
export CARGO_TARGET_DIR="$RUNNER_TEMP/hepta-http-v6"
mkdir -p "$CARGO_TARGET_DIR"
python3 .github/scripts/fix_http_tls_classification.py
cargo fmt --all

# Archive each exact branch tip, then absorb noncanonical tips as history-only
# parents. This preserves all commits but prevents stale trees from overwriting
# the selected W0/Bao/governance implementation.
git fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune --force
mapfile -t refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
: > "$report_dir/archive-tags-v6.tsv"
: > "$report_dir/history-merges-v6.tsv"
for ref in "${refs[@]}"; do
  branch="${ref#origin/}"
  tip="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    [[ "$existing" == "$tip" ]] || tag="$tag-${tip:0:12}"
  fi
  if ! git show-ref --verify --quiet "refs/tags/$tag"; then
    git tag -a "$tag" "$tip" -m "Archive exact tip of $branch before V6 single-main convergence"
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$report_dir/archive-tags-v6.tsv"

  if git merge-base --is-ancestor "$tip" HEAD; then
    printf '%s\talready-contained\n' "$branch" >> "$report_dir/history-merges-v6.tsv"
  else
    git merge --no-ff --no-edit -s ours --allow-unrelated-histories "$tip" \
      -m "merge(history-v6): absorb $branch into canonical main lineage"
    printf '%s\thistory-only\n' "$branch" >> "$report_dir/history-merges-v6.tsv"
  fi
done

python3 - <<'PY'
from __future__ import annotations
import json
import subprocess
from pathlib import Path

primary = "origin/codex/hepta-w0-seven-lanes-handoff-20260908"
supplements = [
    "origin/codex/hepta-bao-connect-20260908",
    "origin/reviewer/ci-governance-simplification-20260908",
    "origin/codex/hepta-final-gap-closure-r3-20260908",
    "origin/codex/hepta-final-gap-closure-r2-20260908",
    "origin/integration/hepta-w0-internal-closure-20260908",
]
resolved = {}
for ref in [primary, *supplements]:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    resolved[ref] = result.stdout.strip() if result.returncode == 0 else None
Path("convergence/source-selection-v6.json").write_text(
    json.dumps(
        {
            "schema": 6,
            "primary": primary,
            "supplements": supplements,
            "resolved_shas": resolved,
            "materialization": "immutable-candidate-matrix",
            "http_tls_classifier": "source-chain-only",
            "qualification_gates": [
                "cargo-fmt",
                "http-client-tests",
                "workspace-check",
                "workspace-clippy",
                "workspace-test",
            ],
            "tree_policy": "normal-merge-current-history-only-superseded",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

refs = subprocess.check_output(
    ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
    text=True,
).splitlines()
refs = sorted(ref for ref in refs if ref != "origin/HEAD")
rows = []
unreachable = []
for ref in refs:
    tip = subprocess.check_output(["git", "rev-parse", ref], text=True).strip()
    ok = subprocess.run(["git", "merge-base", "--is-ancestor", tip, "HEAD"]).returncode == 0
    branch = ref.removeprefix("origin/")
    rows.append({"branch": branch, "sha": tip, "reachable": ok})
    if not ok:
        unreachable.append(branch)
Path("convergence/branch-closure-v6.json").write_text(
    json.dumps(
        {
            "schema": 6,
            "head_before_candidate_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "branches": rows,
            "unreachable": unreachable,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
if unreachable:
    raise SystemExit(f"unreachable branch tips: {unreachable}")
PY

cat > "$report_dir/FINAL_SINGLE_MAIN_V6.md" <<'EOF'
# Final single-main convergence V6

The immutable candidate is materialized from `main`, using the W0 seven-lane
handoff as canonical source. HeptaBao and final-gap heads are normal functional
supplements. The narrow CI-governance cleanup wins its own conflicts. All other
exact branch tips are annotated and included only as history parents.

Five independent runners qualify the same candidate SHA: Rust formatting,
complete HTTP-client targets, workspace check, workspace Clippy with warnings
denied, and workspace tests. A qualified tag and ready ref are published only
when all five jobs succeed. The source candidate itself contains no temporary
convergence workflow or script.
EOF

# Remove every controller before committing the immutable tree.
rm -f \
  .github/convergence-probe.txt \
  .github/scripts/final_main_convergence.sh \
  .github/scripts/final_main_convergence_v2.sh \
  .github/scripts/finalize_single_main_v3.sh \
  .github/scripts/finalize_management_plane.sh \
  .github/scripts/finalize_management_v5.sh \
  .github/scripts/fix_http_tls_classification.py \
  .github/scripts/source_convergence_v5.sh \
  .github/scripts/materialize_source_v6.sh \
  .github/scripts/finalize_management_v6.sh \
  .github/workflows/final-main-convergence.yml \
  .github/workflows/final-main-convergence-v2.yml \
  .github/workflows/final-main-convergence-v3.yml \
  .github/workflows/final-main-convergence-v5.yml \
  .github/workflows/final-main-convergence-v6.yml \
  .github/workflows/finalize-management-plane.yml \
  .github/workflows/finalize-management-v5.yml

cargo fmt --all
git diff --check
git add -A
git commit -s -m "merge: materialize immutable V6 all-branch candidate" \
  -m "Select W0 as canonical code, add Bao and current supplements, retain every superseded tip as tagged history, and remove temporary convergence controllers."
candidate="$(git rev-parse HEAD)"
printf '%s\n' "$candidate" > "$evidence/candidate-sha.txt"
echo "candidate_sha=$candidate" >> "$GITHUB_OUTPUT"

tag="candidate/final-main/v6-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git tag -a "$tag" "$candidate" -m "Immutable V6 all-branch candidate $candidate"
git push origin '+refs/tags/archive/branch-tip/20260908/*:refs/tags/archive/branch-tip/20260908/*'
git push origin "refs/tags/$tag" "+HEAD:refs/heads/$candidate_branch"

# Verify public candidate identity before matrix qualification starts.
remote_candidate="$(git ls-remote --heads origin "refs/heads/$candidate_branch" | awk '{print $1}')"
[[ "$remote_candidate" == "$candidate" ]] || exit 30
