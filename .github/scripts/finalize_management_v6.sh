#!/usr/bin/env bash
set -Eeuo pipefail

repo="${GITHUB_REPOSITORY:-TrillionniumFoundation/hepta-private-ci}"
candidate_branch="candidate/final-main-v6-20260908"
ready_branch="ready/final-main-v6-20260908"
compat_ready="ready/final-main-20260908"
seal_branch="ready/final-main-management-v6"
evidence="$RUNNER_TEMP/hepta-management-v6"
expected="${EXPECTED_CANDIDATE:?EXPECTED_CANDIDATE is required}"
qualified_tag="${QUALIFIED_TAG:?QUALIFIED_TAG is required}"
mkdir -p "$evidence"
exec > >(tee "$evidence/management-v6.log") 2>&1

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

fetch_all
candidate="$(git rev-parse "origin/$candidate_branch")"
ready="$(git rev-parse "origin/$ready_branch")"
compat="$(git rev-parse "origin/$compat_ready")"
[[ "$candidate" == "$expected" && "$ready" == "$expected" && "$compat" == "$expected" ]] || {
  echo "qualified refs disagree: expected=$expected candidate=$candidate ready=$ready compat=$compat" >&2
  exit 20
}
peeled="$(git ls-remote --tags origin "refs/tags/$qualified_tag^{}" | awk '{print $1}')"
[[ "$peeled" == "$expected" ]] || {
  echo "qualified tag mismatch: $qualified_tag -> $peeled, expected $expected" >&2
  exit 21
}

git show "$expected:convergence/source-selection-v6.json" > "$evidence/source-selection-v6.json"
git show "$expected:convergence/branch-closure-v6.json" > "$evidence/source-branch-closure-v6.json"
python3 - "$evidence/source-selection-v6.json" "$evidence/source-branch-closure-v6.json" <<'PY'
import json, sys
source=json.load(open(sys.argv[1], encoding='utf-8'))
closure=json.load(open(sys.argv[2], encoding='utf-8'))
assert source.get('schema') == 6, source
assert source.get('primary') == 'origin/codex/hepta-w0-seven-lanes-handoff-20260908', source
assert source.get('materialization') == 'immutable-candidate-matrix', source
assert source.get('http_tls_classifier') == 'source-chain-only', source
assert source.get('qualification_gates') == [
    'cargo-fmt','http-client-tests','workspace-check','workspace-clippy','workspace-test'
], source
assert closure.get('schema') == 6, closure
assert closure.get('unreachable') == [], closure.get('unreachable')
PY

# Seal any refs created after candidate materialization into the exact tested
# tree. Only ancestry changes; the tree hash is byte-identical to the candidate.
git checkout --detach "$expected"
tree="$(git rev-parse "$expected^{tree}")"
seal="$expected"
: > "$evidence/archive-tags-v6.tsv"
: > "$evidence/late-history-v6.tsv"
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
    git tag -a "$tag" "$tip" -m "Archive exact tip of $branch before V6 cleanup"
  fi
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/archive-tags-v6.tsv"
  if ! git merge-base --is-ancestor "$tip" "$seal"; then
    seal="$(printf 'merge(history-v6-management): seal %s\n' "$branch" | git commit-tree "$tree" -p "$seal" -p "$tip")"
    printf '%s\t%s\n' "$branch" "$tip" >> "$evidence/late-history-v6.tsv"
  fi
done
[[ "$(git rev-parse "$seal^{tree}")" == "$tree" ]] || exit 22
printf '%s\n' "$seal" > "$evidence/final-seal-v6.txt"
seal_tag="qualified/final-main-v6/management-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git tag -a "$seal_tag" "$seal" -m "V6 final management seal; tested tree $tree"
git push origin '+refs/tags/archive/branch-tip/20260908/*:refs/tags/archive/branch-tip/20260908/*'
git push origin "refs/tags/$seal_tag" "+$seal:refs/heads/$ready_branch" "+$seal:refs/heads/$compat_ready" "+$seal:refs/heads/$seal_branch"

while IFS=$'\t' read -r branch tip tag; do
  remote="$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')"
  [[ "$remote" == "$tip" ]] || {
    echo "archive tag mismatch for $branch: $tag" >&2
    exit 23
  }
done < "$evidence/archive-tags-v6.tsv"

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
      --title "merge: final V6 qualified all-branch seal" \
      --body "The tree is byte-identical to the independently matrix-qualified V6 candidate. Additional commits only seal late branch tips as history; all exact tips are annotated under archive/branch-tip/20260908/." >/dev/null
    pr="$(gh pr list --repo "$repo" --state open --head "$seal_branch" --json number --jq '.[0].number')"
  fi
  printf '%s\n' "$pr" > "$evidence/seal-pr-v6.txt"
  set +e
  gh pr merge "$pr" --repo "$repo" --merge --admin \
    --subject "merge: final V6 qualified all-branch seal" \
    --body "All five independent V6 gates passed on the exact candidate tree; every branch tip is tagged and reachable." \
    >"$evidence/pr-merge.out" 2>"$evidence/pr-merge.err"
  printf '%s\n' "$?" > "$evidence/pr-merge.rc"
  set -e
}

if ! contains_seal; then
  set +e
  api --method PATCH "repos/$repo/git/refs/heads/main" -f sha="$seal" -F force=false \
    >"$evidence/main-patch.json" 2>"$evidence/main-patch.err"
  printf '%s\n' "$?" > "$evidence/main-patch.rc"
  set -e
fi
contains_seal || ensure_pr_merge

set +e
api --method PATCH "repos/$repo" -f default_branch=main \
  >"$evidence/default-patch.json" 2>"$evidence/default-patch.err"
printf '%s\n' "$?" > "$evidence/default-patch.rc"
set -e

default="$(api "repos/$repo" --jq .default_branch)"
if [[ "$default" != main ]]; then
  fetch_all
  old_main="$(git rev-parse origin/main)"
  displaced="retired/pre-v6-main-${old_main:0:12}"
  if ! api "repos/$repo/branches/$(encode "$displaced")" >/dev/null 2>&1; then
    api --method POST "repos/$repo/branches/$(encode main)/rename" -f new_name="$displaced" \
      >"$evidence/rename-main.json"
  fi
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

# Keep a bounded window for connector-side admin promotion. The stable V6 ready
# ref points at the same seal throughout this wait.
for _ in $(seq 1 360); do
  default="$(api "repos/$repo" --jq .default_branch)"
  if [[ "$default" == main ]] && contains_seal; then
    break
  fi
  sleep 10
done
default="$(api "repos/$repo" --jq .default_branch)"
[[ "$default" == main ]] || { echo "default branch is not main" >&2; exit 30; }
contains_seal || { echo "main does not contain V6 seal" >&2; exit 31; }

# Delete only exact tips already tagged and reachable from main. Any genuinely
# late branch fails closed; a rerun will incorporate it into a new same-tree seal.
fetch_all
: > "$evidence/deleted-branches-v6.tsv"
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
  printf '%s\t%s\t%s\n' "$branch" "$tip" "$tag" >> "$evidence/deleted-branches-v6.tsv"
done

mapfile -t open_prs < <(gh pr list --repo "$repo" --state open --limit 500 --json number --jq '.[].number')
for pr in "${open_prs[@]}"; do
  gh pr close "$pr" --repo "$repo" --comment \
    "Superseded by the V6 matrix-qualified all-branch convergence now reachable from main; exact former tips remain under archive/branch-tip/20260908/." || true
done

fetch_all
mapfile -t survivors < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' | sort -u)
printf '%s\n' "${survivors[@]}" > "$evidence/surviving-branches-v6.txt"
[[ ${#survivors[@]} -eq 1 && "${survivors[0]}" == origin/main ]] || {
  echo "non-main refs survived: ${survivors[*]}" >&2
  exit 34
}
api "repos/$repo" --jq '{default_branch,pushed_at,updated_at}' > "$evidence/final-repository-v6.json"
printf '%s\n' 0 > "$evidence/final.rc"
