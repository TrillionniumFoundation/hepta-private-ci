set -euo pipefail
out="$RUNNER_TEMP/private16-evidence"
mkdir -p "$out"
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
git merge-base --is-ancestor "$BASE" "$CANDIDATE"
git diff --name-only "$BASE" "$CANDIDATE" > "$out/changed.txt"
test "$(wc -l < "$out/changed.txt")" -eq 16
if grep -vE '^codex-rs/hepta-agentd/src/[^/]+[.]rs$' "$out/changed.txt"; then exit 1; fi
for arm in base candidate; do
  if [ "$arm" = base ]; then ref="$BASE"; else ref="$CANDIDATE"; fi
  src="$RUNNER_TEMP/source-private-$arm"
  git worktree add --detach "$src" "$ref"
  (
    cd "$src"
    test "$(git rev-parse HEAD)" = "$ref"
    git diff --exit-code
    git rev-parse HEAD 'HEAD^{tree}' HEAD:codex-rs/hepta-agentd > "$out/identity-$arm.txt"
    git ls-tree -r HEAD -- codex-rs/hepta-agentd > "$out/source-$arm.tsv"
    test "$(wc -l < "$out/source-$arm.tsv")" -eq 2215
    git ls-tree HEAD -- codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_tests.rs codex-rs/hepta-agentd/src/cell_q24_training_command_connection_tests.rs > "$out/fixture-$arm.txt"
    test "$(wc -l < "$out/fixture-$arm.txt")" -eq 2
  )
done
cmp "$out/fixture-base.txt" "$out/fixture-candidate.txt"
