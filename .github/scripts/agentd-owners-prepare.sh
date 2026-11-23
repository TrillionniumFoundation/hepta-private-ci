set -euo pipefail
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
test "$(git rev-parse "$CANDIDATE^")" = "$BASE"
dst="$RUNNER_TEMP/owners-lint-evidence"
mkdir -p "$dst"
cp .github/scripts/agentd-owners-cases.json "$RUNNER_TEMP/owners-cases.json"
cp .github/scripts/agentd-owners-driver.py "$RUNNER_TEMP/owners-driver.py"
git diff --name-only "$BASE" "$CANDIDATE" -- > "$dst/product-diff.txt"
test "$(wc -l < "$dst/product-diff.txt")" = 2
rg -Fx 'codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_read.rs' "$dst/product-diff.txt"
rg -Fx 'codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs' "$dst/product-diff.txt"
for arm in base candidate; do
  if [ "$arm" = base ]; then ref="$BASE"; else ref="$CANDIDATE"; fi
  git worktree add --quiet --detach "$RUNNER_TEMP/owners-$arm" "$ref"
  git -C "$RUNNER_TEMP/owners-$arm" rev-parse HEAD > "$dst/identity-$arm.txt"
  git -C "$RUNNER_TEMP/owners-$arm" rev-parse 'HEAD^{tree}' > "$dst/tree-$arm.txt"
  git -C "$RUNNER_TEMP/owners-$arm" ls-tree -r HEAD -- CALLERS.toml scripts/hepta_callers_manifest_parts qa/b4-no-bypass/test_original_evaluation_provider_source_closure.py qa/b4-no-bypass/test_original_on_policy_evaluation_source_closure.py > "$dst/guards-$arm.txt"
  cd "$RUNNER_TEMP/owners-$arm"
  for guard in test_original_evaluation_provider_source_closure.py test_original_on_policy_evaluation_source_closure.py; do
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s qa/b4-no-bypass -p "$guard" -v > "$dst/$arm-$guard.log" 2>&1
  done
  cd "$GITHUB_WORKSPACE"
done
cmp "$dst/guards-base.txt" "$dst/guards-candidate.txt"
