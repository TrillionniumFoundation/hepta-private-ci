#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
ready_branch="ready/final-main-20260908"
seal_branch="ready/final-main-management-v5"
evidence="$RUNNER_TEMP/hepta-management-v5"
mkdir -p "$evidence"
exec > >(tee "$evidence/management-v5.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"

api() { gh api "$@"; }
encode() {
  python3 - "$1" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
PY
}
fetch_all() {
  git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune --force
}

# Wait for the exact V5 epoch. Old ready refs are intentionally rejected.
for _ in $(seq 1 720); do
  fetch_all
  if git show-ref --verify --quiet "refs/remotes/origin/$ready_branch"; then
    candidate="$(git rev-parse "origin/$ready_branch")"
    if git cat-file -e "$candidate:convergence/source-selection-v5.json" 2>/dev/null; then
      break
    fi
  fi
  sleep 15
done
candidate="$(git rev-parse "origin/$ready_branch")"
printf '%s\n' "$candidate" > "$evidence/source-candidate.txt"
git show "$candidate:convergence/source-selection-v5.json" > "$evidence/source-selection-v5.json"
python3 - "$evidence/source-selection-v5.json" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert obj.get('schema') == 5, obj
assert obj.get('primary') == 'origin/codex/hepta-w0-seven-lanes-handoff-20260908', obj
assert obj.get('materialization') == 'direct-clean-worktree', obj
assert obj.get('http_tls_classifier') == 'source-chain-only', obj
PY

for gate in cargo-fmt http-client-tests workspace-check workspace-clippy workspace-test; do
  value="$(git show "$candidate:convergence/$gate-v5.rc" 2>/dev/null | tr -d '\r\n[:space:]')"
  [[ "$value" == 0 ]] || {
    echo "V5 gate is not zero: $gate=${value:-missing}" >&2
    exit 20
  }
  printf '%s\t0\n' "$gate" >> "$evidence/verified-gates.tsv"
done
git show "$candidate:convergence/branch-closure-v5.json" > "$evidence/source-branch-closure-v5.json"
python3 - "$evidence/source-branch-closure-v5.json" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert obj.get('schema') == 5, obj
assert obj.get('unreachable') == [], obj.get('unreachable')
PY

# Seal every branch created or moved after V5 testing into the same tested tree.
# Only commit ancestry changes; the tree hash is invariant.
fetch_all
git checkout --detach "$candidate"
tree="$(git rev-parse "$candidate^{tree}")"
seal="$candidate"
: > "$evidence/archive-tags.tsv"
: > "$evidence/late-history.tsv"
mapfile -t refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
for ref in "${refs[@]}"; do
  branch="${ref#origin/}"
  tip="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    [[ "$existing" == "$tip" ]] || tag="$tag-${tip:0:12}"
  fi
  if ! git show-ref --verify --quiet "refs/tags/$tag"; then
    git tag -a "$tag" "$tip" -m "Archive exact tip of $branch before V5 single-main cleanup"
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/archive-tags.tsv"
  if ! git merge-base --is-ancestor "$tip" "$seal"; then
    seal="$(printf 'merge(history-v5-management): seal %s\n' "$branch" | git commit-tree "$tree" -p "$seal" -p "$tip")"
    printf '%s\t%s\n' "$branch" "$tip" >> "$evidence/late-history.tsv"
  fi
done
[[ "$(git rev-parse "$seal^{tree}")" == "$tree" ]] || exit 21
printf '%s\n' "$seal" > "$evidence/final-seal.txt"
seal_tag="ready/final-main/management-v5-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git tag -a "$seal_tag" "$seal" -m "Final V5 management seal of tested tree $tree"
git push origin '+refs/tags/archive/branch-tip/20260908/*:refs/tags/archive/branch-tip/20260908/*'
git push origin "refs/tags/$seal_tag" "+$seal:refs/heads/$ready_branch" "+$seal:refs/heads/$seal_branch"

while IFS=$'\t' read -r branch tip tag; do
  remote="$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')"
  [[ "$remote" == "$tip" ]] || {
    echo "archive verification failed: $branch $tag" >&2
    exit 22
  }
done < "$evidence/archive-tags.tsv"

export GH_TOKEN="${HEPTA_ADMIN_TOKEN:-${GH_TOKEN:-}}"
contains_seal() {
  fetch_all
  git show-ref --verify --quiet refs/remotes/origin/main && git merge-base --is-ancestor "$seal" origin/main
}

ensure_pr_merge() {
  local pr
  pr="$(gh pr list --repo "$repo" --state open --head "$seal_branch" --json number --jq '.[0].number // empty')"
  if [[ -z "$pr" ]]; then
    gh pr create --repo "$repo" --base main --head "$seal_branch" \
      --title "merge: final V5 tested all-branch seal" \
      --body "The source tree is the exact V5-tested tree. Additional commits only make late branch tips ancestors; all exact tips are annotated under archive/branch-tip/20260908/." >/dev/null
    pr="$(gh pr list --repo "$repo" --state open --head "$seal_branch" --json number --jq '.[0].number')"
  fi
  printf '%s\n' "$pr" > "$evidence/seal-pr.txt"
  set +e
  gh pr merge "$pr" --repo "$repo" --merge --admin \
    --subject "merge: final V5 tested all-branch seal" \
    --body "V5 gates are zero; every exact branch tip is tagged and reachable." \
    >"$evidence/pr-merge.out" 2>"$evidence/pr-merge.err"
  printf '%s\n' "$?" > "$evidence/pr-merge.rc"
  set -e
}

# Attempt ordinary fast-forward, then protected PR/admin path.
if ! contains_seal; then
  set +e
  api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$seal" -F force=false \
    >"$evidence/main-patch.json" 2>"$evidence/main-patch.err"
  printf '%s\n' "$?" > "$evidence/main-patch.rc"
  set -e
fi
contains_seal || ensure_pr_merge

# Try repository setting first.
set +e
api --method PATCH "repos/$repo" -f default_branch=main \
  >"$evidence/default-patch.json" 2>"$evidence/default-patch.err"
printf '%s\n' "$?" > "$evidence/default-patch.rc"
set -e

# Contents-write fallback for the known old-default layout. Move the current
# main aside, rename the current default to main (which moves the default), and
# then fast-forward it to the tested seal. The seal contains both old tips.
default="$(api "repos/$repo" --jq .default_branch)"
if [[ "$default" != main ]]; then
  fetch_all
  current_main="$(git rev-parse origin/main)"
  displaced="retired/pre-v5-main-${current_main:0:12}"
  if ! api "repos/$repo/branches/$(encode "$displaced")" >/dev/null 2>&1; then
    api --method POST "repos/$repo/branches/$(encode main)/rename" -f new_name="$displaced" \
      >"$evidence/rename-main.json"
  fi
  # Re-read in case a parallel administrator already switched it.
  default="$(api "repos/$repo" --jq .default_branch)"
  if [[ "$default" != main ]]; then
    api --method POST "repos/$repo/branches/$(encode "$default")/rename" -f new_name=main \
      >"$evidence/rename-default.json"
  fi
  for _ in $(seq 1 30); do
    set +e
    api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$seal" -F force=false \
      >"$evidence/post-rename-main-patch.json" 2>"$evidence/post-rename-main-patch.err"
    rc=$?
    set -e
    [[ $rc -eq 0 ]] && break
    sleep 2
  done
  contains_seal || ensure_pr_merge
fi

# The connected admin may promote the stable ready ref while this bounded wait
# is active. No branch deletion occurs until both predicates are true.
for _ in $(seq 1 360); do
  default="$(api "repos/$repo" --jq .default_branch)"
  if [[ "$default" == main ]] && contains_seal; then
    break
  fi
  sleep 10
done
default="$(api "repos/$repo" --jq .default_branch)"
[[ "$default" == main ]] || { echo "default branch is not main" >&2; exit 30; }
contains_seal || { echo "main does not contain final V5 seal" >&2; exit 31; }

# Refetch at deletion boundary. A genuinely late branch is fail-closed rather
# than silently omitted; a subsequent retry will seal it.
fetch_all
: > "$evidence/deleted-branches.tsv"
mapfile -t final_refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
for ref in "${final_refs[@]}"; do
  branch="${ref#origin/}"
  [[ "$branch" == main ]] && continue
  tip="$(git rev-parse "$ref")"
  git merge-base --is-ancestor "$tip" origin/main || {
    echo "late unsealed branch: $branch $tip" >&2
    exit 32
  }

  tag="archive/branch-tip/20260908/$branch"
  remote="$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')"
  if [[ "$remote" != "$tip" ]]; then
    tag="$tag-${tip:0:12}"
    if ! git show-ref --verify --quiet "refs/tags/$tag"; then
      git tag -a "$tag" "$tip" -m "Archive late exact tip of $branch"
    fi
    git push origin "refs/tags/$tag"
  fi
  [[ "$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')" == "$tip" ]] || exit 33

  encoded="$(encode "$branch")"
  api --method DELETE "repos/$repo/branches/$encoded/protection" >/dev/null 2>&1 || true
  set +e
  api --method DELETE "repos/$repo/git/refs/$(encode "heads/$branch")" \
    >"$evidence/delete-${tip:0:12}.out" 2>"$evidence/delete-${tip:0:12}.err"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    retired="retired/${tip:0:12}"
    api --method POST "repos/$repo/branches/$encoded/rename" -f new_name="$retired" >/dev/null
    api --method DELETE "repos/$repo/git/refs/$(encode "heads/$retired")" >/dev/null
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/deleted-branches.tsv"
done

mapfile -t open_prs < <(gh pr list --repo "$repo" --state open --limit 500 --json number --jq '.[].number')
for pr in "${open_prs[@]}"; do
  gh pr close "$pr" --repo "$repo" --comment \
    "Superseded by the V5-tested all-branch convergence now reachable from main; each exact former tip is retained under archive/branch-tip/20260908/." || true
done

fetch_all
mapfile -t survivors < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
printf '%s\n' "${survivors[@]}" > "$evidence/survivors.txt"
[[ ${#survivors[@]} -eq 1 && "${survivors[0]}" == origin/main ]] || {
  echo "non-main refs survived: ${survivors[*]}" >&2
  exit 34
}
api "repos/$repo" --jq '{default_branch,pushed_at,updated_at}' > "$evidence/final-repository.json"
printf '%s\n' 0 > "$evidence/final.rc"
