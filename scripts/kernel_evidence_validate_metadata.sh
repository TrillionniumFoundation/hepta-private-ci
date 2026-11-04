#!/usr/bin/env bash
set -euo pipefail

: "${SOURCE_SHA:?}"
: "${SOURCE_TREE:?}"
: "${READINESS_RECORDS:?}"
: "${GITHUB_WORKSPACE:?}"

records="$READINESS_RECORDS/metadata"
mkdir -p "$records"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
test -z "$(git status --porcelain=v1 --untracked-files=all)"

python3 - <<'PY'
import unittest

suite = unittest.defaultTestLoader.discover(
    "scripts/tests", pattern="test_kernel_evidence*.py"
)
discovered = suite.countTestCases()
result = unittest.TextTestRunner(verbosity=2).run(suite)
passed = (
    discovered > 0
    and result.testsRun == discovered
    and result.wasSuccessful()
    and not result.skipped
)
print(
    f"kernel_evidence_python_tests discovered={discovered} "
    f"executed={result.testsRun} failures={len(result.failures)} "
    f"errors={len(result.errors)} skipped={len(result.skipped)}"
)
raise SystemExit(0 if passed else 1)
PY
python3 scripts/kernel_evidence_status.py verify
python3 scripts/hepta-docs.py verify

worktree_root="$(mktemp -d "$RUNNER_TEMP/kernel-evidence-map.XXXXXX")"
worktree="$worktree_root/worktree"
cleanup() {
  git -C "$GITHUB_WORKSPACE" worktree remove --force "$worktree" >/dev/null 2>&1 || true
  rm -rf "$worktree_root"
}
trap cleanup EXIT

git worktree add --detach "$worktree" "$SOURCE_SHA"
(
  cd "$worktree"
  test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
  test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
  test -z "$(git status --porcelain=v1 --untracked-files=all)"
  python3 scripts/hepta-implementation-maps.py migrate --module kernel.evidence
  map=docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json
  test -s "$map"
  cp "$map" "$records/IMPLEMENTATION_MAP.current.json"
  git add -- "$map"
  git -c user.name='Hepta kernel evidence qualification' \
      -c user.email='hepta-kernel-evidence-ci@users.noreply.github.com' \
      commit -s -m 'chore(kernel.evidence): bind temporary qualification map'
  generated_sha="$(git rev-parse HEAD)"
  generated_tree="$(git rev-parse HEAD^{tree})"
  python3 scripts/hepta-implementation-maps.py verify \
    --expected-sha "$generated_sha" \
    --expected-tree "$generated_tree"
  {
    printf 'source_head_sha=%s\n' "$SOURCE_SHA"
    printf 'source_head_tree=%s\n' "$SOURCE_TREE"
    printf 'temporary_map_commit=%s\n' "$generated_sha"
    printf 'temporary_map_tree=%s\n' "$generated_tree"
    printf 'implementation_map_sha256=%s\n' "$(sha256sum "$map" | awk '{print $1}')"
  } >"$records/implementation-map-binding.txt"
)

test -s "$records/IMPLEMENTATION_MAP.current.json"
test -s "$records/implementation-map-binding.txt"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
