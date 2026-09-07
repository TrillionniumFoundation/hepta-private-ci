#!/usr/bin/env bash
set -euo pipefail

TARGET_ROOT="${1:?target checkout path is required}"
EXPECTED_HEAD="a04ba23781879c67d4545a4480ce94468c07337c"
EXPECTED_TREE="03dd11db161c7d3c55003552103cd3aa914e80b5"
SEALED_BASE="b97b856b0a23625ea98eccd97e701134aa967e2f"
PATCH_CARRIER="b2a87e5d9b3542cc522b5e7760956261d2d8b52d"
CARRIER_BRANCH="ops/pr456-followup-publisher-20260907-r1"
DEST_BRANCH="integration/final-main-tree-followup-20260907-r1"
PATCH_SHA256="df5d4db1f3f9ec761bdf27bbd008f4808f91aa6b5fd9942d7848a57ed72079e6"
PATCH_GZIP_SHA256="1a9ba79dc43fca1db27ac59f9b014f461cfbfd4fc9bdcc25cb02b447ed51ef52"
PATCH_B64_SHA256="b2d71770aa5223a74b5f5d06a1bc8cec3593a4fb79610e27828fd43c0a4fd944"
WORK="${RUNNER_TEMP:?}/pr456-followup"

rm -rf "$WORK"
mkdir -p "$WORK"
cd "$TARGET_ROOT"

test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test "$(git rev-parse 'HEAD^{tree}')" = "$EXPECTED_TREE"
test "$(git show -s --format=%P HEAD)" = "$SEALED_BASE"
test -z "$(git status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"

git fetch --no-tags origin "refs/heads/$CARRIER_BRANCH:refs/remotes/origin/pr456-followup-carrier"
git cat-file -e "$PATCH_CARRIER^{commit}"
git show "$PATCH_CARRIER:.github/workflows/pr456-followup-publisher-20260907.yml" > "$WORK/carrier.yml"
python3 - "$WORK/carrier.yml" "$WORK/followup.patch.gz.b64" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
start = next(i for i, line in enumerate(lines) if "<<'PATCH_B64'" in line)
end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PATCH_B64")
payload = "".join(line.strip() for line in lines[start + 1:end])
if not payload:
    raise SystemExit("empty patch payload")
Path(sys.argv[2]).write_text(payload)
PY

test "$(sha256sum "$WORK/followup.patch.gz.b64" | cut -d' ' -f1)" = "$PATCH_B64_SHA256"
base64 -d "$WORK/followup.patch.gz.b64" > "$WORK/followup.patch.gz"
test "$(sha256sum "$WORK/followup.patch.gz" | cut -d' ' -f1)" = "$PATCH_GZIP_SHA256"
gzip -dc "$WORK/followup.patch.gz" > "$WORK/followup.patch"
test "$(sha256sum "$WORK/followup.patch" | cut -d' ' -f1)" = "$PATCH_SHA256"

git apply --check "$WORK/followup.patch"
git apply "$WORK/followup.patch"
git diff --check

git diff --name-only | LC_ALL=C sort > "$WORK/changed.txt"
printf '%s\n' \
  .g1/trillionnium_os_external_evidence/EXECUTOR.md \
  .g1/trillionnium_os_external_evidence/tests/test_trusted_executor.py \
  .g1/trillionnium_os_external_evidence/trusted_executor.py \
  | LC_ALL=C sort > "$WORK/expected.txt"
diff -u "$WORK/expected.txt" "$WORK/changed.txt"

cd .g1/trillionnium_os_external_evidence
rm -rf __pycache__ tests/__pycache__
python3 -m py_compile admission_service.py trusted_executor.py tests/*.py
python3 -m unittest discover -s tests -v
rm -rf __pycache__ tests/__pycache__
cd "$TARGET_ROOT"

test -z "$(git status --porcelain=v1 --untracked-files=all | awk '$1 == "??" {print $2}')"
git diff --check

git config user.name "Qian QI"
git config user.email "102159240+ProfHepta@users.noreply.github.com"
git add \
  .g1/trillionnium_os_external_evidence/EXECUTOR.md \
  .g1/trillionnium_os_external_evidence/tests/test_trusted_executor.py \
  .g1/trillionnium_os_external_evidence/trusted_executor.py
new_tree="$(git write-tree)"
message="fix(g1): terminalize every post-start evidence failure

Close the exact-head review gaps for authorization expiry after output-pipe closure, bundle traversal failures, process setup/procfs cleanup uncertainty, and durable non-overwriting terminal receipts after STARTED.

This single-parent source candidate retains unprovisioned policies and grants no target, device, destructive, signing, promotion, deployment, gap-transition or public-release authority."
new_commit="$(printf '%s\n' "$message" | git commit-tree "$new_tree" -p "$SEALED_BASE")"

test "$(git show -s --format=%P "$new_commit")" = "$SEALED_BASE"
test "$(git rev-parse "$new_commit^{tree}")" = "$new_tree"
if git ls-remote --exit-code --heads origin "refs/heads/$DEST_BRANCH" >/dev/null 2>&1; then
  echo "destination branch already exists" >&2
  exit 1
fi

git push origin "$new_commit:refs/heads/$DEST_BRANCH"
printf '%s\n' \
  "candidate_commit=$new_commit" \
  "candidate_tree=$new_tree" \
  "source_predecessor=$EXPECTED_HEAD" \
  "sealed_base=$SEALED_BASE" \
  "patch_sha256=$PATCH_SHA256" \
  | tee "$WORK/publication.txt"
