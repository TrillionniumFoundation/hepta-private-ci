set -euo pipefail
out="$RUNNER_TEMP/material-projection-evidence"
mkdir -p "$out"
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
git merge-base --is-ancestor "$BASE" "$CANDIDATE"
git diff --name-only "$BASE" "$CANDIDATE" > "$out/changed.txt"
test "$(wc -l < "$out/changed.txt")" -eq 2
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
    test -s "$out/source-$arm.tsv"
    git ls-tree HEAD -- codex-rs/hepta-agentd/src/circuit_original_evaluation_model_material_tests.rs codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_codec_tests.rs codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service_support_tests.rs > "$out/fixture-$arm.txt"
    test "$(wc -l < "$out/fixture-$arm.txt")" -eq 3
  )
done
cmp "$out/fixture-base.txt" "$out/fixture-candidate.txt"
git diff --exit-code "$BASE" "$CANDIDATE" -- .github/scripts scripts codex-rs/hepta-agentd/BUILD.bazel
test "$(git rev-parse "$BASE":codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_member.rs)" = 40d2c6d4ae804cdf0a582bfde4d32b9412e4e32c
test "$(git rev-parse "$CANDIDATE":codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_member.rs)" = f1e964d70ffb4e22a4663176525b274f6221ace7
test "$(git rev-parse "$BASE":codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_wire.rs)" = cb4df67fd0f3340c27c05cada46bbc11f080bc50
test "$(git rev-parse "$CANDIDATE":codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_wire.rs)" = 5a78300a2ca8c2982ffdb1e7946c4bf0c76e4dc7
