#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
controller_branch="ops/final-main-convergence-v3-20260908"
ready_branch="ready/final-main-20260908"
work_branch="hepta-final-source-v5"
report_dir="convergence"
evidence="$RUNNER_TEMP/hepta-source-convergence-v5"
patcher="$RUNNER_TEMP/fix_http_tls_classification.py"
mkdir -p "$evidence"
exec > >(tee "$evidence/source-v5.log") 2>&1

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
    echo "unresolved paths remain:" >&2
    git diff --name-only --diff-filter=U >&2
    return 1
  fi
}

merge_normal() {
  local ref="$1" preference="$2" label="$3"
  if ! git show-ref --verify --quiet "refs/remotes/$ref"; then
    printf '%s\tmissing\n' "$ref" >> "$report_dir/canonical-merges-v5.tsv"
    return 0
  fi
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$ref" >> "$report_dir/canonical-merges-v5.tsv"
    return 0
  fi
  echo "Normal merge $ref; conflict preference=$preference"
  set +e
  git merge --no-ff --no-edit -X "$preference" "$ref" -m "merge(convergence-v5): $label"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    resolve_conflicts "$preference"
    git commit -s --no-edit
  fi
  printf '%s\tnormal-merge\t%s\n' "$ref" "$preference" >> "$report_dir/canonical-merges-v5.tsv"
}

: > "$report_dir/canonical-merges-v5.tsv"
primary="origin/codex/hepta-w0-seven-lanes-handoff-20260908"
git show-ref --verify --quiet "refs/remotes/$primary" || {
  echo "required W0 handoff is missing: $primary" >&2
  exit 10
}
merge_normal "$primary" theirs "canonical W0 seven-lane handoff"

# Bao is primarily additive and therefore retains W0 on conflicts. The narrow
# CI-governance cleanup is deletion-focused and wins its own conflicts.
merge_normal "origin/codex/hepta-bao-connect-20260908" ours "HeptaBao final-use boundary"
merge_normal "origin/reviewer/ci-governance-simplification-20260908" theirs "retire one-shot CI governance"
for ref in \
  "origin/codex/hepta-final-gap-closure-r3-20260908" \
  "origin/codex/hepta-final-gap-closure-r2-20260908" \
  "origin/integration/hepta-w0-internal-closure-20260908"; do
  merge_normal "$ref" ours "supplement ${ref#origin/}"
done

# Close the reproduced reqwest/rustls nested source-chain classification gap.
python3 .github/scripts/fix_http_tls_classification.py

# Apply only compiler- and Clippy-provided mechanical rewrites. These commands
# are advisory; the strict gates below remain the acceptance authority.
export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_INCREMENTAL=0
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_TEST_DEBUG=0
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
export CARGO_TARGET_DIR="$RUNNER_TEMP/hepta-target-v5"
mkdir -p "$CARGO_TARGET_DIR"
cargo fmt --all
cargo fix --locked --workspace --all-targets --allow-dirty --allow-staged 2>&1 | tee "$evidence/cargo-fix.log" || true
cargo clippy --fix --locked --workspace --all-targets --allow-dirty --allow-staged 2>&1 | tee "$evidence/clippy-fix.log" || true
cargo fmt --all

# Capture each exact remote tip and preserve it by annotated tag. Current source
# heads were merged normally above; every residual head is history-only so old
# trees cannot overwrite the selected implementation.
git fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune --force
mapfile -t remote_refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
: > "$report_dir/archive-tags-v5.tsv"
: > "$report_dir/history-merges-v5.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  tip="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    [[ "$existing" == "$tip" ]] || tag="$tag-${tip:0:12}"
  fi
  if ! git show-ref --verify --quiet "refs/tags/$tag"; then
    git tag -a "$tag" "$tip" -m "Archive exact tip of $branch before single-main convergence"
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$report_dir/archive-tags-v5.tsv"

  if git merge-base --is-ancestor "$tip" HEAD; then
    printf '%s\talready-contained\n' "$branch" >> "$report_dir/history-merges-v5.tsv"
  else
    git merge --no-ff --no-edit -s ours --allow-unrelated-histories "$tip" \
      -m "merge(history-v5): absorb $branch into canonical main lineage"
    printf '%s\thistory-only\n' "$branch" >> "$report_dir/history-merges-v5.tsv"
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
Path("convergence/source-selection-v5.json").write_text(
    json.dumps(
        {
            "schema": 5,
            "primary": primary,
            "supplements": supplements,
            "resolved_shas": resolved,
            "materialization": "direct-clean-worktree",
            "http_tls_classifier": "source-chain-only",
            "mechanical_fixes": ["cargo-fix", "clippy-fix", "cargo-fmt"],
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
Path("convergence/branch-closure-v5.json").write_text(
    json.dumps(
        {
            "schema": 5,
            "head_before_validation": subprocess.check_output(
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

cat > "$report_dir/FINAL_SINGLE_MAIN_V5.md" <<'EOF'
# Final single-main convergence V5

The source tree is materialized directly from `main`, with the W0 seven-lane
handoff as the canonical implementation source. HeptaBao and final-gap heads are
normal supplements; the deletion-focused CI-governance branch wins conflicts in
its narrow scope. Every other exact branch tip is archived by annotated tag and
absorbed only as history, so stale trees cannot replace current code.

The final committed tree excludes all temporary convergence controllers and is
accepted only after Rust formatting, the full HTTP-client target, workspace
check, workspace Clippy with warnings denied, and workspace tests all return
zero. Independent scientific, owner, hardware, operator and future-duration
claims are not manufactured by this repository operation.
EOF

# Remove every temporary controller before testing the exact product tree.
rm -f \
  .github/convergence-probe.txt \
  .github/scripts/final_main_convergence.sh \
  .github/scripts/final_main_convergence_v2.sh \
  .github/scripts/finalize_single_main_v3.sh \
  .github/scripts/finalize_management_plane.sh \
  .github/scripts/fix_http_tls_classification.py \
  .github/scripts/source_convergence_v5.sh \
  .github/workflows/final-main-convergence.yml \
  .github/workflows/final-main-convergence-v2.yml \
  .github/workflows/final-main-convergence-v3.yml \
  .github/workflows/finalize-management-plane.yml \
  .github/workflows/final-main-convergence-v5.yml

run_gate() {
  local name="$1"
  shift
  echo "::group::$name"
  set +e
  "$@" 2>&1 | tee "$evidence/$name.log"
  local rc=${PIPESTATUS[0]}
  set -e
  printf '%s\n' "$rc" > "$report_dir/$name-v5.rc"
  echo "::endgroup::"
  return "$rc"
}

run_gate cargo-fmt cargo fmt --all -- --check
run_gate http-client-tests cargo test --locked -p codex-http-client --all-targets
run_gate workspace-check cargo check --locked --workspace --all-targets
run_gate workspace-clippy cargo clippy --locked --workspace --all-targets -- -D warnings
run_gate workspace-test cargo test --locked --workspace --all-targets

git diff --check
git add -A
git commit -s -m "merge: materialize every branch into one tested main lineage" \
  -m "Select W0 as canonical source, merge current functional supplements, retain every superseded tip as tagged history, and record strict zero-valued gate receipts."
final_sha="$(git rev-parse HEAD)"
printf '%s\n' "$final_sha" > "$evidence/final-sha.txt"
ready_tag="ready/final-main/v5-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git tag -a "$ready_tag" "$final_sha" -m "Tested V5 final-main candidate $final_sha"

git push origin '+refs/tags/archive/branch-tip/20260908/*:refs/tags/archive/branch-tip/20260908/*'
git push origin "refs/tags/$ready_tag"
git push origin "HEAD:refs/heads/$controller_branch" "+HEAD:refs/heads/$ready_branch"

# Verify the fixed ready ref contains the exact V5 epoch and all zero receipts.
for gate in cargo-fmt http-client-tests workspace-check workspace-clippy workspace-test; do
  [[ "$(git show "$final_sha:convergence/$gate-v5.rc" | tr -d '\r\n[:space:]')" == 0 ]]
done
git cat-file -e "$final_sha:convergence/source-selection-v5.json"
git cat-file -e "$final_sha:convergence/branch-closure-v5.json"

# Best-effort immediate fast-forward. The management finalizer performs the
# protected/default-branch transaction and all ref deletion.
export GH_TOKEN="${HEPTA_ADMIN_TOKEN:-${GH_TOKEN:-}}"
gh api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$final_sha" -F force=false \
  >"$evidence/main-fast-forward.json" 2>"$evidence/main-fast-forward.err" || true
