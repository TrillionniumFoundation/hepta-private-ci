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

mkdir -p "$READINESS_RECORDS/merge"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
construction_log="$READINESS_RECORDS/merge/construction.log"
: >"$construction_log"

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
printf 'MERGE_SHA=%s\nMERGE_TREE=%s\n' "$merge_sha" "$merge_tree" >>"$GITHUB_ENV"
printf 'merge_sha=%s\nmerge_tree=%s\n' "$merge_sha" "$merge_tree" >>"$construction_log"

git checkout --detach "$merge_sha" >>"$construction_log" 2>&1
command='set -euo pipefail; test "$(git rev-parse HEAD)" = "$MERGE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$MERGE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli'
started="$(date +%s%3N)"
set +e
bash -lc "$command" >"$READINESS_RECORDS/merge/tests.log" 2>&1
code=$?
set -e
finished="$(date +%s%3N)"
git checkout --detach "$SOURCE_SHA" >>"$construction_log" 2>&1

python3 scripts/kernel_evidence_qualification_receipt.py \
  --kind deterministic_merge \
  --source-head-sha "$SOURCE_SHA" \
  --source-head-tree "$SOURCE_TREE" \
  --base-sha "$BASE_SHA" \
  --deterministic-merge-sha "$merge_sha" \
  --tested-object-sha "$merge_sha" \
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
