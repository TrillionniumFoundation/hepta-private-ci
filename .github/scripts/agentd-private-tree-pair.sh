set -euo pipefail
out="$RUNNER_TEMP/private16-evidence"
mkdir -p "$out"
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
git merge-base --is-ancestor "$BASE" "$CANDIDATE"
git diff --name-only "$BASE" "$CANDIDATE" > "$out/changed.txt"
sort "$out/changed.txt" > "$out/all-paths.txt"
cat > "$out/expected-paths.txt" <<'PATHS'
CALLERS.toml
codex-rs/hepta-agentd/src/artifact_original_head_client.rs
codex-rs/hepta-agentd/src/authority_host_publication_grant_store.rs
codex-rs/hepta-agentd/src/authority_host_publication_grant_store_tests.rs
codex-rs/hepta-agentd/src/authority_host_run_start_context.rs
codex-rs/hepta-agentd/src/authority_host_run_start_inputs.rs
codex-rs/hepta-agentd/src/authority_host_run_start_store.rs
codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs
codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs
codex-rs/hepta-agentd/src/cell_q24_training_candidate_tests.rs
codex-rs/hepta-agentd/src/cell_q24_training_source.rs
codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_episode.rs
codex-rs/hepta-agentd/src/circuit_on_policy_evaluation_records.rs
codex-rs/hepta-agentd/src/circuit_q24_successor.rs
codex-rs/hepta-agentd/src/circuit_q24_successor_worker.rs
codex-rs/hepta-agentd/src/neuron_generation_current_store.rs
codex-rs/hepta-agentd/src/production_post_a_artifacts.rs
codex-rs/hepta-agentd/src/production_post_a_continuation.rs
codex-rs/hepta-agentd/src/selected_memory_service.rs
qa/b4-no-bypass/test_original_c_grant_consumer_source_closure.py
qa/b4-no-bypass/test_original_c_grant_source_closure.py
qa/b4-no-bypass/test_original_training_bootstrap_source_closure.py
scripts/hepta_callers_manifest_parts/part-0000.toml.gz
scripts/hepta_callers_manifest_parts/part-0001.toml.gz
PATHS
LC_ALL=C sort -o "$out/expected-paths.txt" "$out/expected-paths.txt"
LC_ALL=C sort -o "$out/all-paths.txt" "$out/all-paths.txt"
cmp "$out/expected-paths.txt" "$out/all-paths.txt"
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
