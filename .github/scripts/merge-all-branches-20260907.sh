#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_BRANCH="${TARGET_BRANCH:-main}"
WORKFLOW_PATH="${WORKFLOW_PATH:-.github/workflows/merge-all-branches-to-main-20260907.yml}"
SCRIPT_PATH="${SCRIPT_PATH:-.github/scripts/merge-all-branches-20260907.sh}"
REPORT_PATH="${REPORT_PATH:-${RUNNER_TEMP}/merge-all-branches-report.tsv}"
MERGE_LOG_PATH="${MERGE_LOG_PATH:-${RUNNER_TEMP}/merge-all-branches.log}"
MANIFEST_PATH="${MANIFEST_PATH:-.merge-all-branches/final-workflows.json}"

exec > >(tee -a "${MERGE_LOG_PATH}") 2>&1

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git config core.hooksPath /dev/null
git config merge.conflictStyle zdiff3
git config rerere.enabled false

printf 'pass\tbranch\tsha\tresult\tconflict_paths\n' > "${REPORT_PATH}"

fetch_all_branches() {
  git fetch --prune --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
}

list_remote_branches() {
  git for-each-ref \
    --sort=refname \
    --sort=committerdate \
    --format='%(committerdate:unix)%09%(refname)' \
    refs/remotes/origin \
    | while IFS=$'\t' read -r commit_time ref; do
        branch="${ref#refs/remotes/origin/}"
        case "${branch}" in
          HEAD|"${TARGET_BRANCH}"|integration/all-branches-staging-*)
            continue
            ;;
        esac
        printf '%s\t%s\t%s\n' "${commit_time}" "${branch}" "${ref}"
      done
}

RESOLVED_CONFLICT_COUNT=0

resolve_incoming_conflicts() {
  local branch="$1"
  local conflict_count=0
  local path

  if ! git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    echo "Merge failed for ${branch} without an active merge state." >&2
    return 1
  fi

  while IFS= read -r -d '' path; do
    conflict_count=$((conflict_count + 1))
    if git ls-files -u -- "${path}" \
         | awk '$3 == 3 { found = 1 } END { exit(found ? 0 : 1) }'; then
      git checkout --theirs -- "${path}"
      git add -- "${path}"
    else
      git rm -f --ignore-unmatch -- "${path}"
    fi
  done < <(git diff --name-only --diff-filter=U -z)

  if git diff --name-only --diff-filter=U | grep -q .; then
    echo "Unresolved paths remain after incoming-side resolution for ${branch}." >&2
    git status --short >&2
    return 1
  fi

  git add -A
  git commit --signoff \
    -m "merge(branch): absorb ${branch} into aggregate [skip ci]" \
    -m "Conflict policy: branches are processed from older to newer commit dates; unresolved paths take the incoming branch version."
  RESOLVED_CONFLICT_COUNT="${conflict_count}"
}

merge_one_branch() {
  local pass="$1"
  local branch="$2"
  local ref="$3"
  local sha
  sha="$(git rev-parse "${ref}")"

  if git merge-base --is-ancestor "${sha}" HEAD; then
    printf '%s\t%s\t%s\talready-contained\t0\n' \
      "${pass}" "${branch}" "${sha}" >> "${REPORT_PATH}"
    return 0
  fi

  echo "::group::Merging ${branch} (${sha})"
  if git -c core.hooksPath=/dev/null merge \
    --no-ff \
    --no-edit \
    --signoff \
    --allow-unrelated-histories \
    -X theirs \
    -m "merge(branch): absorb ${branch} into aggregate [skip ci]" \
    "${sha}"; then
    printf '%s\t%s\t%s\tmerged\t0\n' \
      "${pass}" "${branch}" "${sha}" >> "${REPORT_PATH}"
  else
    RESOLVED_CONFLICT_COUNT=0
    resolve_incoming_conflicts "${branch}"
    printf '%s\t%s\t%s\tmerged-with-incoming-conflict-resolution\t%s\n' \
      "${pass}" "${branch}" "${sha}" "${RESOLVED_CONFLICT_COUNT}" >> "${REPORT_PATH}"
  fi
  echo "::endgroup::"
}

fetch_all_branches
main_before="$(git rev-parse "refs/remotes/origin/${TARGET_BRANCH}")"
backup_branch="backup/main-before-all-branches-${GITHUB_RUN_ID}-${main_before:0:12}"
staging_branch="integration/all-branches-staging-${GITHUB_RUN_ID}"

echo "Main before merge: ${main_before}"
echo "Creating runtime backup: ${backup_branch}"
git push origin "${main_before}:refs/heads/${backup_branch}"

git switch --detach "${main_before}"
git switch -c "automation/merge-all-branches-${GITHUB_RUN_ID}"

stable=0
for pass in 1 2 3; do
  echo "Starting merge pass ${pass}."
  fetch_all_branches
  merged_this_pass=0

  while IFS=$'\t' read -r _commit_time branch ref; do
    before="$(git rev-parse HEAD)"
    merge_one_branch "${pass}" "${branch}" "${ref}"
    after="$(git rev-parse HEAD)"
    if [[ "${before}" != "${after}" ]]; then
      merged_this_pass=$((merged_this_pass + 1))
    fi
  done < <(list_remote_branches)

  fetch_all_branches
  pending=0
  while IFS=$'\t' read -r _commit_time branch ref; do
    sha="$(git rev-parse "${ref}")"
    if ! git merge-base --is-ancestor "${sha}" HEAD; then
      echo "Branch moved or remains unmerged after pass ${pass}: ${branch} (${sha})"
      pending=$((pending + 1))
    fi
  done < <(list_remote_branches)

  echo "Pass ${pass}: merge commits added=${merged_this_pass}, pending branches=${pending}."
  if [[ "${pending}" -eq 0 ]]; then
    stable=1
    break
  fi
done

if [[ "${stable}" -ne 1 ]]; then
  echo "Remote branches did not stabilize within three merge passes." >&2
  exit 1
fi

# Retire the temporary publisher surfaces from the desired final tree.
git rm -f --ignore-unmatch -- "${WORKFLOW_PATH}" "${SCRIPT_PATH}"
git add -A

fully_merged_tree="$(git write-tree)"
fully_merged_head="$(git rev-parse HEAD)"
export MAIN_BEFORE="${main_before}"
export FULLY_MERGED_TREE="${fully_merged_tree}"
export MANIFEST_PATH

echo "Fully merged local head: ${fully_merged_head}"
echo "Fully merged desired tree: ${fully_merged_tree}"

# Preserve exact desired workflow blobs under non-workflow carrier paths. This
# permits the ordinary Actions token to publish the objects without granting it
# authority to update .github/workflows.
python3 - <<'PY'
import json
import os
import pathlib
import subprocess

manifest_path = pathlib.Path(os.environ["MANIFEST_PATH"])
carrier_root = manifest_path.parent / "workflow-blobs"
carrier_root.mkdir(parents=True, exist_ok=True)

desired = []
unique_blobs = {}
raw = subprocess.check_output(
    ["git", "ls-files", "-s", "--", ".github/workflows"],
    text=True,
)
for line in raw.splitlines():
    metadata, path = line.split("\t", 1)
    mode, sha, stage = metadata.split()
    if stage != "0":
        raise SystemExit(f"non-stage-zero workflow entry: {path}")
    desired.append({"path": path, "mode": mode, "sha": sha})
    unique_blobs.setdefault(sha, f".merge-all-branches/workflow-blobs/{sha}")

for sha, carrier in sorted(unique_blobs.items()):
    data = subprocess.check_output(["git", "cat-file", "blob", sha])
    carrier_path = pathlib.Path(carrier)
    carrier_path.parent.mkdir(parents=True, exist_ok=True)
    carrier_path.write_bytes(data)

baseline_raw = subprocess.check_output(
    [
        "git",
        "ls-tree",
        "-r",
        "--name-only",
        os.environ["MAIN_BEFORE"],
        "--",
        ".github/workflows",
    ],
    text=True,
)
baseline_paths = [line for line in baseline_raw.splitlines() if line]
temporary_paths = [str(manifest_path)] + sorted(unique_blobs.values())
manifest = {
    "schema": "org.trillionnium.merge-all-branches.workflow-transport.v1",
    "main_before": os.environ["MAIN_BEFORE"],
    "fully_merged_tree": os.environ["FULLY_MERGED_TREE"],
    "desired": sorted(desired, key=lambda row: row["path"]),
    "baseline_paths": sorted(baseline_paths),
    "temporary_paths": temporary_paths,
}
manifest_path.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

# Restore main's previous workflow tree, stage carrier blobs and manifest, and
# form a workflow-neutral content commit directly on the old main.
git rm -r -f --ignore-unmatch -- .github/workflows
if git cat-file -e "${main_before}:.github/workflows" 2>/dev/null; then
  git checkout "${main_before}" -- .github/workflows
fi
git add -A

while IFS=$'\t' read -r sha carrier; do
  git update-index --add --cacheinfo "100644,${sha},${carrier}"
done < <(
  python3 - <<'PY'
import json
import os
manifest = json.load(open(os.environ["MANIFEST_PATH"], encoding="utf-8"))
seen = set()
for row in manifest["desired"]:
    sha = row["sha"]
    if sha in seen:
        continue
    seen.add(sha)
    print(f"{sha}\t.merge-all-branches/workflow-blobs/{sha}")
PY
)

content_tree="$(git write-tree)"
squash_commit="$(
  printf '%s\n\n%s\n' \
    'merge(all-branches): consolidate non-workflow content [skip ci]' \
    'Workflow blobs are carried outside .github/workflows for authenticated final placement.' \
    | git commit-tree "${content_tree}" -p "${main_before}"
)"

# Add every remote branch tip as a parent without altering the content tree.
# A bounded parent fan-out avoids one excessively wide octopus commit.
current="${squash_commit}"
batch=()
batch_index=0

flush_batch() {
  if [[ ${#batch[@]} -eq 0 ]]; then
    return
  fi
  batch_index=$((batch_index + 1))
  parent_args=(-p "${current}")
  for parent in "${batch[@]}"; do
    parent_args+=(-p "${parent}")
  done
  current="$(
    printf 'merge(all-branches): ancestry batch %s [skip ci]\n' "${batch_index}" \
      | git commit-tree "${content_tree}" "${parent_args[@]}"
  )"
  batch=()
}

fetch_all_branches
while IFS=$'\t' read -r _commit_time branch ref; do
  sha="$(git rev-parse "${ref}")"
  if git merge-base --is-ancestor "${sha}" "${current}"; then
    continue
  fi
  batch+=("${sha}")
  if [[ ${#batch[@]} -ge 16 ]]; then
    flush_batch
  fi
done < <(list_remote_branches)
flush_batch

staging_head="${current}"
staging_tree="$(git rev-parse "${staging_head}^{tree}")"

echo "Publishing workflow-neutral staging head ${staging_head} to ${staging_branch}."
git push origin "${staging_head}:refs/heads/${staging_branch}"
fetch_all_branches

remote_staging="$(git rev-parse "refs/remotes/origin/${staging_branch}")"
if [[ "${remote_staging}" != "${staging_head}" ]]; then
  echo "Remote staging mismatch: expected ${staging_head}, observed ${remote_staging}." >&2
  exit 1
fi

verification_failures=0
while IFS=$'\t' read -r _commit_time branch ref; do
  sha="$(git rev-parse "${ref}")"
  if ! git merge-base --is-ancestor "${sha}" "${staging_head}"; then
    printf 'verify\t%s\t%s\tnot-contained\t0\n' \
      "${branch}" "${sha}" >> "${REPORT_PATH}"
    verification_failures=$((verification_failures + 1))
  fi
done < <(list_remote_branches)

if [[ "${verification_failures}" -ne 0 ]]; then
  echo "${verification_failures} branch tips are not ancestors of staging head." >&2
  exit 1
fi

{
  echo "main_before=${main_before}"
  echo "backup_branch=${backup_branch}"
  echo "staging_branch=${staging_branch}"
  echo "staging_head=${staging_head}"
  echo "staging_tree=${staging_tree}"
  echo "fully_merged_tree=${fully_merged_tree}"
  echo "branch_rows=$(( $(wc -l < "${REPORT_PATH}") - 1 ))"
} >> "${GITHUB_OUTPUT}"
