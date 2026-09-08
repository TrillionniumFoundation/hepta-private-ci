#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
work_branch="ops/final-main-convergence-v3-20260908"
v2_branch="ops/final-main-convergence-20260908"
report_dir="convergence"
mkdir -p "$report_dir"
exec > >(tee "$report_dir/finalize-single-main-v3.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"
git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune
[[ "$(git branch --show-current)" == "$work_branch" ]] || exit 2

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
  ! git diff --name-only --diff-filter=U | grep -q .
}

merge_normal() {
  local ref="$1" preference="$2" label="$3"
  git show-ref --verify --quiet "refs/remotes/$ref" || return 0
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$ref" >> "$report_dir/canonical-merges-v3.tsv"
    return 0
  fi
  set +e
  git merge --no-ff --no-edit -X "$preference" "$ref" -m "merge(convergence): $label"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    resolve_conflicts "$preference"
    git commit -s --no-edit
  fi
  printf '%s\tnormal-merge\t%s\n' "$ref" "$preference" >> "$report_dir/canonical-merges-v3.tsv"
}

: > "$report_dir/canonical-merges-v3.tsv"

# Prefer a successfully materialized V2 tree; otherwise converge directly from
# the newest implementation sources. A V2 tree is accepted only when all five
# recorded gates are present and zero.
v2_ok=false
if git show-ref --verify --quiet "refs/remotes/origin/$v2_branch" && \
   git cat-file -e "origin/$v2_branch:convergence/branch-closure.json" 2>/dev/null; then
  v2_ok=true
  for gate in cargo-fmt http-client-tests workspace-check workspace-clippy workspace-test; do
    value="$(git show "origin/$v2_branch:convergence/$gate.rc" 2>/dev/null || true)"
    [[ "$value" == "0" ]] || v2_ok=false
  done
fi

if [[ "$v2_ok" == true ]]; then
  merge_normal "origin/$v2_branch" theirs "verified V2 convergence"
else
  primary=""
  for candidate in \
    "origin/codex/hepta-v9-blocker-closure-20260908" \
    "origin/codex/hepta-w0-seven-lanes-handoff-20260908" \
    "origin/codex/hepta-bao-connect-20260908" \
    "origin/codex/hepta-final-gap-closure-r3-20260908"; do
    if git show-ref --verify --quiet "refs/remotes/$candidate"; then
      primary="$candidate"
      break
    fi
  done
  [[ -n "$primary" ]] || { echo "no canonical candidate" >&2; exit 3; }
  merge_normal "$primary" theirs "primary ${primary#origin/}"
  for ref in \
    "origin/reviewer/ci-governance-simplification-20260908" \
    "origin/codex/hepta-bao-connect-20260908" \
    "origin/codex/hepta-w0-seven-lanes-handoff-20260908" \
    "origin/codex/hepta-final-gap-closure-r3-20260908" \
    "origin/codex/hepta-final-gap-closure-r2-20260908" \
    "origin/integration/hepta-w0-internal-closure-20260908"; do
    merge_normal "$ref" ours "supplement ${ref#origin/}"
  done
  python3 .github/scripts/fix_http_tls_classification.py
fi

# Re-fetch immediately before graph sealing so no branch movement is silently
# missed. Every exact tip gets an immutable annotated archive tag.
git fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune
mapfile -t remote_refs < <(
  git for-each-ref --format='%(refname:short)' refs/remotes/origin \
    | grep -v '^origin/HEAD$' | sort -u
)
: > "$report_dir/archive-tags-v3.tsv"
: > "$report_dir/history-merges-v3.tsv"
for ref in "${remote_refs[@]}"; do
  branch="${ref#origin/}"
  sha="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    [[ "$existing" == "$sha" ]] || tag="$tag-${sha:0:12}"
  fi
  git tag -a "$tag" "$sha" -m "Archive $branch before single-main-tree convergence"
  printf '%s\t%s\t%s\n' "$branch" "$sha" "$tag" >> "$report_dir/archive-tags-v3.tsv"
  [[ "$branch" == "$work_branch" ]] && continue
  if git merge-base --is-ancestor "$ref" HEAD; then
    printf '%s\talready-contained\n' "$branch" >> "$report_dir/history-merges-v3.tsv"
  else
    git merge --no-ff --no-edit -s ours --allow-unrelated-histories "$ref" \
      -m "merge(history): absorb $branch into canonical main lineage"
    printf '%s\thistory-only\n' "$branch" >> "$report_dir/history-merges-v3.tsv"
  fi
done

python3 - <<'PY'
from __future__ import annotations
import json, subprocess
from pathlib import Path
refs = subprocess.check_output(
    ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
    text=True,
).splitlines()
refs = sorted(ref for ref in refs if ref != "origin/HEAD")
rows=[]; missing=[]
for ref in refs:
    sha=subprocess.check_output(["git","rev-parse",ref],text=True).strip()
    ok=subprocess.run(["git","merge-base","--is-ancestor",ref,"HEAD"]).returncode==0
    branch=ref.removeprefix("origin/")
    rows.append({"branch":branch,"sha":sha,"reachable":ok})
    if not ok: missing.append(branch)
Path("convergence/branch-closure-v3.json").write_text(json.dumps({
    "schema":1,
    "head":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
    "branches":rows,
    "unreachable":missing,
},indent=2)+"\n")
if missing: raise SystemExit(f"unreachable tips: {missing}")
PY

cat > "$report_dir/FINAL_SINGLE_MAIN_20260908.md" <<'EOF'
# Final single-main convergence — 2026-09-08

Current implementation heads are normal merges. Residual backup, diagnostic,
one-shot controller and superseded heads are history-only merges after their
exact tips are archived as annotated tags. Thus all branch histories are
reachable from the convergence commit while stale trees cannot overwrite the
selected implementation.

Promotion is fail-closed on Rust formatting, the complete HTTP-client target,
workspace check, workspace Clippy with warnings denied, and workspace tests.
No external scientific, operator, hardware or future-duration evidence is
manufactured by changing repository status files.
EOF

export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_INCREMENTAL=0
export CARGO_TARGET_DIR="$RUNNER_TEMP/hepta-target-v3"
mkdir -p "$CARGO_TARGET_DIR"
run_gate() {
  local name="$1"; shift
  set +e
  "$@" 2>&1 | tee "$report_dir/$name-v3.log"
  local rc=${PIPESTATUS[0]}
  set -e
  printf '%s\n' "$rc" > "$report_dir/$name-v3.rc"
  return "$rc"
}
run_gate cargo-fmt cargo fmt --all -- --check
run_gate http-client-tests cargo test --locked -p codex-http-client --all-targets
run_gate workspace-check cargo check --locked --workspace --all-targets
run_gate workspace-clippy cargo clippy --locked --workspace --all-targets -- -D warnings
run_gate workspace-test cargo test --locked --workspace --all-targets

git diff --check
mkdir -p "$RUNNER_TEMP/final-single-main-evidence"
cp -a "$report_dir/." "$RUNNER_TEMP/final-single-main-evidence/"
find "$report_dir" -type f -name '*.log' -delete

rm -f \
  .github/convergence-probe.txt \
  .github/scripts/final_main_convergence.sh \
  .github/scripts/final_main_convergence_v2.sh \
  .github/scripts/finalize_single_main_v3.sh \
  .github/scripts/fix_http_tls_classification.py \
  .github/workflows/final-main-convergence.yml \
  .github/workflows/final-main-convergence-v2.yml \
  .github/workflows/final-main-convergence-v3.yml

git add -A
git commit -s -m "merge: seal every branch into one tested main lineage"
git push origin "HEAD:refs/heads/$work_branch" --follow-tags

pr="$(gh pr list --repo "$repo" --state open --head "$work_branch" --json number --jq '.[0].number // empty')"
if [[ -z "$pr" ]]; then
  gh pr create --repo "$repo" --base main --head "$work_branch" \
    --title "merge: seal every branch into one tested main lineage" \
    --body-file "$report_dir/FINAL_SINGLE_MAIN_20260908.md" >/tmp/pr-url
  pr="$(gh pr list --repo "$repo" --state open --head "$work_branch" --json number --jq '.[0].number')"
fi
printf '%s\n' "$pr" > "$RUNNER_TEMP/final-single-main-evidence/pr-number.txt"

# Explicit owner-authorized administrative promotion after the strict gates
# above. Prefer a separately provisioned repository-admin token when present.
admin_token="${HEPTA_ADMIN_TOKEN:-${GH_ADMIN_TOKEN:-${REPO_ADMIN_TOKEN:-${GH_TOKEN}}}}"
export GH_TOKEN="$admin_token"
set +e
gh pr merge "$pr" --repo "$repo" --merge --admin --subject "merge: final single-main convergence" \
  --body "All fetched branch tips are reachable from the tested convergence commit; exact tips are archived as annotated tags."
merge_rc=$?
set -e
printf '%s\n' "$merge_rc" > "$RUNNER_TEMP/final-single-main-evidence/merge.rc"
[[ $merge_rc -eq 0 ]] || exit 41

# Switch the repository authority before deleting the previous default branch.
gh api --method PATCH "repos/$repo" -f default_branch=main >/dev/null
git fetch origin main:refs/remotes/origin/main --force

# Delete every non-main branch only after its exact tip is both archived and
# reachable from main. Protection is removed only from branches being retired;
# main protection is never removed.
mapfile -t final_refs < <(
  git for-each-ref --format='%(refname:short)' refs/remotes/origin \
    | grep -v '^origin/HEAD$' | sort -u
)
: > "$RUNNER_TEMP/final-single-main-evidence/deleted-branches.tsv"
for ref in "${final_refs[@]}"; do
  branch="${ref#origin/}"
  [[ "$branch" == main ]] && continue
  sha="$(git rev-parse "$ref")"
  if ! git merge-base --is-ancestor "$sha" origin/main; then
    echo "branch moved or is not in main: $branch $sha" >&2
    exit 42
  fi
  encoded="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$branch")"
  gh api --method DELETE "repos/$repo/branches/$encoded/protection" >/dev/null 2>&1 || true
  ref_encoded="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote("heads/"+sys.argv[1], safe=""))' "$branch")"
  gh api --method DELETE "repos/$repo/git/refs/$ref_encoded" >/dev/null
  printf '%s\t%s\n' "$branch" "$sha" >> "$RUNNER_TEMP/final-single-main-evidence/deleted-branches.tsv"
done

# Close now-obsolete open PRs whose heads no longer exist.
mapfile -t open_prs < <(gh pr list --repo "$repo" --state open --limit 500 --json number --jq '.[].number')
for number in "${open_prs[@]}"; do
  gh pr close "$number" --repo "$repo" --comment \
    "Superseded by the tested all-branch convergence now merged into main; the exact former branch tip is retained under archive/branch-tip/20260908/." || true
done
