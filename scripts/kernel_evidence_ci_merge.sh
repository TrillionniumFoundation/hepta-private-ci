#!/usr/bin/env bash
set -euo pipefail

: "${SOURCE_SHA:?}"
: "${SOURCE_TREE:?}"
: "${BASE_SHA:?}"
: "${WORKFLOW_SHA:?}"
: "${GITHUB_RUN_ID:?}"
: "${GITHUB_RUN_ATTEMPT:?}"
: "${RUNNER_IMAGE:?}"
: "${TARGET_TRIPLE:?}"
: "${READINESS_RECORDS:?}"

mkdir -p "$READINESS_RECORDS/merge" "$READINESS_RECORDS/merge-metadata/metadata"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
construction_log="$READINESS_RECORDS/merge/construction.log"
: >"$construction_log"

initial_state="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$initial_state" ]]; then
  {
    printf 'deterministic merge refused a dirty source worktree\n'
    printf '%s\n' "$initial_state"
  } >>"$construction_log"
  printf 'MERGE_SHA=\nMERGE_TREE=\n' >>"$GITHUB_ENV"
  exit 0
fi

set +e
merge_tree="$(git merge-tree --write-tree "$BASE_SHA" "$SOURCE_SHA" 2>>"$construction_log")"
construct_code=$?
set -e
if [[ $construct_code -ne 0 || ! "$merge_tree" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'deterministic merge construction failed with exit %s\n' "$construct_code" >>"$construction_log"
  printf 'MERGE_SHA=\nMERGE_TREE=\n' >>"$GITHUB_ENV"
  exit 0
fi

export GIT_AUTHOR_NAME='Hepta kernel evidence readiness'
export GIT_AUTHOR_EMAIL='hepta-kernel-evidence-ci@users.noreply.github.com'
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
export GIT_AUTHOR_DATE='2000-01-01T00:00:00Z'
export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
merge_sha="$(printf 'Synthetic kernel evidence readiness merge for PR %s\n' "${PR_NUMBER:-0}" | git commit-tree "$merge_tree" -p "$BASE_SHA" -p "$SOURCE_SHA")"
[[ "$merge_sha" =~ ^[0-9a-f]{40}$ ]]
export MERGE_SHA="$merge_sha"
export MERGE_TREE="$merge_tree"
printf 'MERGE_SHA=%s\nMERGE_TREE=%s\n' "$MERGE_SHA" "$MERGE_TREE" >>"$GITHUB_ENV"
printf 'merge_sha=%s\nmerge_tree=%s\n' "$MERGE_SHA" "$MERGE_TREE" >>"$construction_log"

git checkout --detach "$MERGE_SHA" >>"$construction_log" 2>&1
command='set -euo pipefail; test "$(git rev-parse HEAD)" = "$MERGE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$MERGE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli; cd "$GITHUB_WORKSPACE"; SOURCE_SHA="$MERGE_SHA" SOURCE_TREE="$MERGE_TREE" READINESS_RECORDS="$READINESS_RECORDS/merge-metadata" bash scripts/kernel_evidence_validate_metadata.sh >"$READINESS_RECORDS/merge-metadata/metadata/metadata.log" 2>&1'
started="$(date +%s%3N)"
set +e
timeout --signal=TERM --kill-after=30s 5400s \
  bash -lc "$command" >"$READINESS_RECORDS/merge/tests.log" 2>&1
code=$?
set -e
merge_state="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$merge_state" ]]; then
  {
    printf '\ndeterministic merge qualification dirtied the immutable merge worktree\n'
    printf '%s\n' "$merge_state"
  } >>"$READINESS_RECORDS/merge/tests.log"
  code=125
fi
finished="$(date +%s%3N)"

git checkout --detach -f "$SOURCE_SHA" >>"$construction_log" 2>&1
git clean -fd >>"$construction_log" 2>&1
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
restored_state="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$restored_state" ]]; then
  {
    printf '\nsource worktree was not restored after deterministic merge qualification\n'
    printf '%s\n' "$restored_state"
  } >>"$READINESS_RECORDS/merge/tests.log"
  code=125
fi

python3 scripts/kernel_evidence_qualification_receipt.py \
  --kind deterministic_merge \
  --source-head-sha "$SOURCE_SHA" \
  --source-head-tree "$SOURCE_TREE" \
  --base-sha "$BASE_SHA" \
  --deterministic-merge-sha "$MERGE_SHA" \
  --tested-object-sha "$MERGE_SHA" \
  --workflow-sha "$WORKFLOW_SHA" \
  --workflow-run-id "$GITHUB_RUN_ID" \
  --workflow-run-attempt "$GITHUB_RUN_ATTEMPT" \
  --runner-image "$RUNNER_IMAGE" \
  --target-triple "$TARGET_TRIPLE" \
  --command "$command" \
  --started-at-unix-ms "$started" \
  --finished-at-unix-ms "$finished" \
  --exit-code "$code" \
  --log "$READINESS_RECORDS/merge/tests.log" \
  --output "$READINESS_RECORDS/deterministic_merge.json"
