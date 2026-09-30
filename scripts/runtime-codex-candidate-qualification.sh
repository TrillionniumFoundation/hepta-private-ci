#!/usr/bin/env bash
set -euo pipefail

mode="${1:?usage: runtime-codex-candidate-qualification.sh <exact-head|synthetic-merge>}"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

results="qualification/runtime-codex/results.jsonl"
log_dir="qualification/runtime-codex/logs"
receipt_dir="qualification/runtime-codex/receipt"
rm -rf qualification/runtime-codex
mkdir -p "$log_dir" "$receipt_dir"

base_ref="${RUNTIME_CODEX_BASE_REF:-main}"
git fetch --no-tags origin "+refs/heads/${base_ref}:refs/remotes/origin/${base_ref}"
base_head="$(git rev-parse "refs/remotes/origin/${base_ref}")"
target="$(rustc -vV | sed -n 's/^host: //p')"
export RUNTIME_CODEX_BASE_REF="$base_ref"
export RUNTIME_CODEX_BASE_HEAD="$base_head"
export RUNTIME_CODEX_CURRENT_BASE_HEAD="$base_head"
export RUNTIME_CODEX_TARGET_TRIPLE="$target"

run() {
  local name="$1"
  shift
  python3 scripts/runtime-codex-qualification.py run \
    --results "$results" \
    --log-dir "$log_dir" \
    --name "$name" \
    -- "$@"
}

run_cargo() {
  local name="$1"
  shift
  python3 scripts/runtime-codex-qualification.py run \
    --results "$results" \
    --log-dir "$log_dir" \
    --name "$name" \
    --cwd codex-rs \
    -- "$@"
}

if [[ "$mode" == "exact-head" ]]; then
  export RUNTIME_CODEX_EXPECTED_HEAD="$(git rev-parse HEAD)"
  export RUNTIME_CODEX_EXPECTED_TREE="$(git rev-parse 'HEAD^{tree}')"
elif [[ "$mode" == "synthetic-merge" ]]; then
  source_head="$(git rev-parse HEAD)"
  git config user.name 'runtime.codex qualification'
  git config user.email 'runtime-codex-qualification@invalid'
  git merge --no-ff --no-edit "$base_head"
  export RUNTIME_CODEX_SOURCE_HEAD="$source_head"
  export RUNTIME_CODEX_MERGE_HEAD="$(git rev-parse HEAD)"
  export RUNTIME_CODEX_MERGE_TREE="$(git rev-parse 'HEAD^{tree}')"
else
  printf 'unsupported qualification mode: %s\n' "$mode" >&2
  exit 2
fi

run lane-b-truth python3 scripts/hepta-lane-b-truth.py verify
run receipt-helper python3 -m py_compile scripts/runtime-codex-qualification.py
run_cargo format cargo fmt --all -- --check

if [[ "$mode" == "exact-head" ]]; then
  run_cargo agent-protocol cargo test --locked -p codex-hepta-agent-protocol
  run_cargo infer-core cargo test --locked -p codex-hepta-infer-core
  run_cargo codex-adapter cargo test --locked -p codex-hepta-codex-adapter
  run_cargo agentd-owner cargo test --locked -p codex-hepta-agentd --lib lane_b_runtime
  run_cargo worker-host cargo test --locked -p codex-hepta-infer-worker-host
  run_cargo crash-matrix cargo test --locked -p codex-hepta-infer-worker-host --test runtime_codex_crash_matrix
  run_cargo product-e2e cargo test --locked -p codex-hepta-agentd runtime_codex_product_caller_commits_one_authorized_terminal_turn
  run_cargo strict-lint cargo clippy --locked \
    -p codex-hepta-agent-protocol \
    -p codex-hepta-infer-core \
    -p codex-hepta-codex-adapter \
    -p codex-hepta-agentd \
    -p codex-hepta-infer-worker-host \
    --all-targets --no-deps -- -D warnings
  required=(lane-b-truth receipt-helper format agent-protocol infer-core codex-adapter agentd-owner worker-host crash-matrix product-e2e strict-lint)
else
  run_cargo compile cargo check --locked \
    -p codex-hepta-agent-protocol \
    -p codex-hepta-infer-core \
    -p codex-hepta-codex-adapter \
    -p codex-hepta-agentd \
    -p codex-hepta-infer-worker-host \
    --all-targets
  run_cargo owner-journal cargo test --locked \
    -p codex-hepta-agent-protocol \
    -p codex-hepta-infer-core \
    -p codex-hepta-agentd --lib lane_b_runtime
  run_cargo crash-matrix cargo test --locked -p codex-hepta-infer-worker-host --test runtime_codex_crash_matrix
  run_cargo product-e2e cargo test --locked -p codex-hepta-agentd runtime_codex_product_caller_commits_one_authorized_terminal_turn
  run_cargo strict-lint cargo clippy --locked \
    -p codex-hepta-agent-protocol \
    -p codex-hepta-infer-core \
    -p codex-hepta-codex-adapter \
    -p codex-hepta-agentd \
    -p codex-hepta-infer-worker-host \
    --all-targets --no-deps -- -D warnings
  required=(lane-b-truth receipt-helper format compile owner-journal crash-matrix product-e2e strict-lint)
fi

python3 scripts/runtime-codex-qualification.py receipt \
  --results "$results" \
  --output-dir "$receipt_dir" \
  --mode "$mode"

gate=(python3 scripts/runtime-codex-qualification.py gate --results "$results" --receipt "$receipt_dir/runtime-codex-qualification-receipt.json")
for name in "${required[@]}"; do
  gate+=(--require "$name")
done
"${gate[@]}"
