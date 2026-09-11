#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 <base-sha> <head-sha>" >&2
  exit 64
fi
BASE_SHA="$1"
HEAD_SHA="$2"
SHA_RE='^[0-9a-f]{40}$'
[[ "${BASE_SHA}" =~ ${SHA_RE} ]] || { echo "invalid base sha" >&2; exit 65; }
[[ "${HEAD_SHA}" =~ ${SHA_RE} ]] || { echo "invalid head sha" >&2; exit 65; }

git cat-file -e "${BASE_SHA}^{commit}"
git cat-file -e "${HEAD_SHA}^{commit}"
test "$(git rev-parse HEAD)" = "${HEAD_SHA}"
read -r OBSERVED_HEAD DIRECT_PARENT EXTRA <<< "$(git rev-list --parents -n 1 "${HEAD_SHA}")"
test "${OBSERVED_HEAD}" = "${HEAD_SHA}"
test "${DIRECT_PARENT}" = "${BASE_SHA}"
test -z "${EXTRA:-}"
test -z "$(git status --porcelain --untracked-files=no)"

HEAD_TREE="$(git rev-parse "${HEAD_SHA}^{tree}")"
export GIT_AUTHOR_NAME='hepta-lane-g-ci'
export GIT_AUTHOR_EMAIL='hepta-lane-g-ci@users.noreply.github.com'
export GIT_COMMITTER_NAME="${GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_AUTHOR_EMAIL}"
export GIT_AUTHOR_DATE='2000-01-01T00:00:00Z'
export GIT_COMMITTER_DATE="${GIT_AUTHOR_DATE}"
MERGE_SHA="$(printf '%s
' 'Lane G ordered synthetic merge' |   git commit-tree "${HEAD_TREE}" -p "${BASE_SHA}" -p "${HEAD_SHA}")"

git reset --hard "${MERGE_SHA}"
read -r OBSERVED_MERGE FIRST_PARENT SECOND_PARENT EXTRA <<<   "$(git rev-list --parents -n 1 HEAD)"
test "${OBSERVED_MERGE}" = "${MERGE_SHA}"
test "${FIRST_PARENT}" = "${BASE_SHA}"
test "${SECOND_PARENT}" = "${HEAD_SHA}"
test -z "${EXTRA:-}"
test "$(git rev-parse HEAD^{tree})" = "${HEAD_TREE}"
test -z "$(git status --porcelain --untracked-files=no)"
printf 'ordered_merge_sha=%s
ordered_merge_tree=%s
' "${MERGE_SHA}" "${HEAD_TREE}"
