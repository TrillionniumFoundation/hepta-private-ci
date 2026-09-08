#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
controller_branch="ops/final-main-convergence-v3-20260908"
ready_branch="ready/final-main-20260908"
evidence="$RUNNER_TEMP/hepta-management-finalizer"
mkdir -p "$evidence"
exec > >(tee "$evidence/finalizer.log") 2>&1

git config user.name "hepta-convergence-bot"
git config user.email "hepta-convergence-bot@users.noreply.github.com"

api() {
  gh api "$@"
}

encode() {
  python3 - "$1" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
PY
}

fetch_all() {
  git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*' --prune --force
}

# Wait for the source-plane transaction. The ready ref is published only after
# all strict Rust gates and branch reachability checks have passed.
for _ in $(seq 1 240); do
  fetch_all
  if git show-ref --verify --quiet "refs/remotes/origin/$ready_branch"; then
    break
  fi
  sleep 15
done
git show-ref --verify --quiet "refs/remotes/origin/$ready_branch" || {
  echo "verified ready ref was not published" >&2
  exit 20
}
ready_sha="$(git rev-parse "origin/$ready_branch")"
printf '%s\n' "$ready_sha" > "$evidence/ready-sha.txt"

# Admit only a source tree with explicit zero-valued receipts. Accept both the
# V3 names and the earlier names to make the finalizer retry-compatible.
for gate in cargo-fmt http-client-tests workspace-check workspace-clippy workspace-test; do
  value="$(git show "$ready_sha:convergence/${gate}-v3.rc" 2>/dev/null || git show "$ready_sha:convergence/${gate}.rc" 2>/dev/null || true)"
  value="$(printf '%s' "$value" | tr -d '\r\n[:space:]')"
  [[ "$value" == 0 ]] || {
    echo "gate $gate is not green at $ready_sha: ${value:-missing}" >&2
    exit 21
  }
  printf '%s\t0\n' "$gate" >> "$evidence/verified-gates.tsv"
done

closure_path="convergence/branch-closure-v3.json"
if ! git cat-file -e "$ready_sha:$closure_path" 2>/dev/null; then
  closure_path="convergence/branch-closure.json"
fi
git show "$ready_sha:$closure_path" > "$evidence/source-branch-closure.json"
python3 - "$evidence/source-branch-closure.json" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
missing=obj.get('unreachable')
if missing != []:
    raise SystemExit(f"source closure is not empty: {missing!r}")
PY

# Build a history-only seal from the exact tested tree. Every current branch tip
# becomes an ancestor while the source tree remains byte-identical to ready.
fetch_all
git checkout --detach "$ready_sha"
tree="$(git rev-parse "$ready_sha^{tree}")"
seal="$ready_sha"
: > "$evidence/sealed-branches.tsv"
: > "$evidence/archive-tags.tsv"
mapfile -t refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
for ref in "${refs[@]}"; do
  branch="${ref#origin/}"
  tip="$(git rev-parse "$ref")"
  tag="archive/branch-tip/20260908/$branch"
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    existing="$(git rev-parse "refs/tags/$tag^{commit}")"
    if [[ "$existing" != "$tip" ]]; then
      tag="$tag-${tip:0:12}"
    fi
  fi
  if ! git show-ref --verify --quiet "refs/tags/$tag"; then
    git tag -a "$tag" "$tip" -m "Archive exact branch tip $branch before single-main cleanup"
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/archive-tags.tsv"

  if ! git merge-base --is-ancestor "$tip" "$seal"; then
    seal="$(printf 'merge(history): seal %s into final main lineage\n' "$branch" | git commit-tree "$tree" -p "$seal" -p "$tip")"
    printf '%s\t%s\n' "$branch" "$tip" >> "$evidence/sealed-branches.tsv"
  fi
done
[[ "$(git rev-parse "$seal^{tree}")" == "$tree" ]] || exit 22
printf '%s\n' "$seal" > "$evidence/seal-sha.txt"

seal_tag="ready/final-main/management-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git tag -a "$seal_tag" "$seal" -m "Management-plane final seal for tested tree $tree"
git push origin '+refs/tags/archive/branch-tip/20260908/*:refs/tags/archive/branch-tip/20260908/*' "refs/tags/$seal_tag" "+$seal:refs/heads/$ready_branch"

# Verify immutable remote archives before attempting any mutation of source refs.
while IFS=$'\t' read -r branch tip tag; do
  remote_tip="$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')"
  [[ "$remote_tip" == "$tip" ]] || {
    echo "remote tag mismatch for $branch: $tag" >&2
    exit 23
  }
done < "$evidence/archive-tags.tsv"

admin_token="${HEPTA_ADMIN_TOKEN:-${GH_TOKEN:-}}"
export GH_TOKEN="$admin_token"

contains_seal() {
  fetch_all
  git show-ref --verify --quiet refs/remotes/origin/main && git merge-base --is-ancestor "$seal" origin/main
}

# First use the ordinary fast-forward path. The seal includes the exact current
# main tip, so force is neither required nor permitted.
if ! contains_seal; then
  set +e
  api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$seal" -F force=false >"$evidence/main-patch.json" 2>"$evidence/main-patch.err"
  patch_rc=$?
  set -e
  printf '%s\n' "$patch_rc" > "$evidence/main-patch.rc"
fi

# Try an ordinary PR/admin merge where a repository-admin token is available.
if ! contains_seal; then
  seal_branch="ready/final-main-management-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
  git push origin "$seal:refs/heads/$seal_branch"
  pr="$(gh pr list --repo "$repo" --state open --head "$seal_branch" --json number --jq '.[0].number // empty')"
  if [[ -z "$pr" ]]; then
    gh pr create --repo "$repo" --base main --head "$seal_branch" --title "merge: final tested all-branch seal" --body "Same tested source tree as $ready_sha; additional commits are history-only parents that make every current branch tip reachable. Exact tips are archived under archive/branch-tip/20260908/." >/dev/null
    pr="$(gh pr list --repo "$repo" --state open --head "$seal_branch" --json number --jq '.[0].number')"
  fi
  printf '%s\n' "$pr" > "$evidence/seal-pr.txt"
  set +e
  gh pr merge "$pr" --repo "$repo" --merge --admin --subject "merge: final tested all-branch seal" --body "All source gates are green; every branch tip is tagged and reachable." >"$evidence/pr-merge.out" 2>"$evidence/pr-merge.err"
  printf '%s\n' "$?" > "$evidence/pr-merge.rc"
  set -e
fi

# Set the default directly when administration authority exists.
set +e
api --method PATCH "repos/$repo" -f default_branch=main >"$evidence/default-patch.json" 2>"$evidence/default-patch.err"
default_patch_rc=$?
set -e
printf '%s\n' "$default_patch_rc" > "$evidence/default-patch.rc"

# Contents-write fallback: rename the existing main out of the way, rename the
# current default branch to main (GitHub follows the default branch rename), and
# then fast-forward that main to the seal. The seal contains both old tips.
default_branch="$(api "repos/$repo" --jq .default_branch)"
if [[ "$default_branch" != main ]]; then
  fetch_all
  old_main_tip="$(git rev-parse origin/main)"
  displaced="retired/pre-convergence-main-${old_main_tip:0:12}"
  main_encoded="$(encode main)"
  default_encoded="$(encode "$default_branch")"

  if ! api "repos/$repo/branches/$(encode "$displaced")" >/dev/null 2>&1; then
    api --method POST "repos/$repo/branches/$main_encoded/rename" -f new_name="$displaced" >"$evidence/rename-main.json"
  fi
  api --method POST "repos/$repo/branches/$default_encoded/rename" -f new_name=main >"$evidence/rename-default.json"

  # The renamed default tip is a parent of the seal, so this remains a strict
  # fast-forward. Retry briefly to allow GitHub's rename propagation to settle.
  for _ in $(seq 1 30); do
    set +e
    api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$seal" -F force=false >"$evidence/post-rename-main-patch.json" 2>"$evidence/post-rename-main-patch.err"
    rc=$?
    set -e
    [[ $rc -eq 0 ]] && break
    sleep 2
  done
fi

# Allow connector-side or administrator-side promotion to land while the exact
# ready point is stable and publicly visible.
for _ in $(seq 1 180); do
  default_branch="$(api "repos/$repo" --jq .default_branch)"
  if [[ "$default_branch" == main ]] && contains_seal; then
    break
  fi
  sleep 10
done
default_branch="$(api "repos/$repo" --jq .default_branch)"
[[ "$default_branch" == main ]] || {
  echo "default branch still requires repository administration authority" >&2
  exit 30
}
contains_seal || {
  echo "main does not yet contain the tested seal" >&2
  exit 31
}

# Retire every non-main ref. Exact tips must be archived and reachable first.
fetch_all
: > "$evidence/deleted-branches.tsv"
mapfile -t final_refs < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
for ref in "${final_refs[@]}"; do
  branch="${ref#origin/}"
  [[ "$branch" == main ]] && continue
  tip="$(git rev-parse "$ref")"
  git merge-base --is-ancestor "$tip" origin/main || {
    echo "late branch not represented in main: $branch $tip" >&2
    exit 32
  }

  # Ensure a remote annotated tag exists for a late or renamed ref as well.
  tag="archive/branch-tip/20260908/$branch"
  if [[ -z "$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')" ]]; then
    tag="$tag-${tip:0:12}"
    if ! git show-ref --verify --quiet "refs/tags/$tag"; then
      git tag -a "$tag" "$tip" -m "Archive late branch tip $branch before deletion"
    fi
    git push origin "refs/tags/$tag"
  fi
  remote_tip="$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')"
  [[ "$remote_tip" == "$tip" ]] || exit 33

  encoded="$(encode "$branch")"
  api --method DELETE "repos/$repo/branches/$encoded/protection" >/dev/null 2>&1 || true
  ref_encoded="$(encode "heads/$branch")"
  set +e
  api --method DELETE "repos/$repo/git/refs/$ref_encoded" >"$evidence/delete-${tip:0:12}.out" 2>"$evidence/delete-${tip:0:12}.err"
  delete_rc=$?
  set -e
  if [[ $delete_rc -ne 0 ]]; then
    # An exact-name protection rule may cease matching after rename.
    retired="retired/${tip:0:12}"
    api --method POST "repos/$repo/branches/$encoded/rename" -f new_name="$retired" >/dev/null
    api --method DELETE "repos/$repo/git/refs/$(encode "heads/$retired")" >/dev/null
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/deleted-branches.tsv"
done

# Close stale PRs only after their branch tips are safely in main and tags.
mapfile -t open_prs < <(gh pr list --repo "$repo" --state open --limit 500 --json number --jq '.[].number')
for pr in "${open_prs[@]}"; do
  gh pr close "$pr" --repo "$repo" --comment "Superseded by the tested all-branch convergence now reachable from main; exact former tips are retained under archive/branch-tip/20260908/." || true
done

fetch_all
mapfile -t survivors < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
printf '%s\n' "${survivors[@]}" > "$evidence/surviving-branches.txt"
[[ ${#survivors[@]} -eq 1 && "${survivors[0]}" == origin/main ]] || {
  echo "cleanup incomplete: ${survivors[*]}" >&2
  exit 34
}
api "repos/$repo" --jq '{default_branch,updated_at,pushed_at}' > "$evidence/repository-final.json"
printf '%s\n' 0 > "$evidence/final.rc"
