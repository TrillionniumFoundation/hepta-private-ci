#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 6 ]]; then
  echo "usage: $0 PACKAGE LANE SOURCE_SHA BASE_SHA TESTED_SHA OUTPUT_DIR" >&2
  exit 64
fi

package="$1"
lane="$2"
source_sha="$3"
base_sha="$4"
tested_sha="$5"
output_dir="$6"
repo_root="$(git rev-parse --show-toplevel)"

case "$package" in
  codex-hepta-infer-core|codex-hepta-infer-worker-host|codex-hepta-agentd) ;;
  *) echo "unsupported package: $package" >&2; exit 64 ;;
esac
case "$lane" in
  source-head|base-merge) ;;
  *) echo "unsupported lane: $lane" >&2; exit 64 ;;
esac

[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$base_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$tested_sha" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$tested_sha"
git diff --quiet
git diff --cached --quiet
test -z "$(git status --porcelain --untracked-files=normal)"

mkdir -p "$output_dir"
export TESTED_SHA="$tested_sha"
export HEPTA_CI_LANE="$lane"
export CARGO_TARGET_DIR="${RUNNER_TEMP:?}/inference-worker-${lane}-${package}"

features=()
if [[ "$package" == "codex-hepta-infer-worker-host" ]]; then
  features=(--features experimental-local-model)
fi

overall=0
run_record() {
  local label="$1"
  local minimum="$2"
  shift 2
  local args=(
    python3 ../scripts/hepta_ci_exec.py
    --output "$output_dir/${label}.json"
  )
  if [[ "$minimum" -gt 0 ]]; then
    args+=(--minimum-tests "$minimum")
  fi
  args+=(-- "$@")
  set +e
  "${args[@]}"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    overall=1
  fi
}

pushd "$repo_root/codex-rs" >/dev/null
run_record library 1 cargo nextest run --locked --package "$package" "${features[@]}" --lib
run_record binaries 0 cargo test --locked --package "$package" "${features[@]}" --bins
run_record check 0 cargo check --locked --package "$package" "${features[@]}" --all-targets
run_record clippy 0 cargo clippy --locked --package "$package" "${features[@]}" --all-targets --no-deps -- -D warnings
if [[ "$package" == "codex-hepta-infer-worker-host" ]]; then
  run_record product-e2e 1 cargo test --locked --package "$package" \
    --features experimental-local-model \
    real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone \
    -- --nocapture --test-threads=1
fi
popd >/dev/null

receipt_args=(
  emit
  --repo-root "$repo_root"
  --source-sha "$source_sha"
  --base-sha "$base_sha"
  --tested-sha "$tested_sha"
  --lane "$lane"
  --package "$package"
  --runner-os "${RUNNER_OS:-Linux}"
  --runner-arch "${RUNNER_ARCH:-X64}"
  --runner-name "${RUNNER_NAME:-github-actions}"
  --runner-environment github-hosted
  --expected-label library
  --expected-label binaries
  --expected-label check
  --expected-label clippy
  --record "library=$output_dir/library.json"
  --record "binaries=$output_dir/binaries.json"
  --record "check=$output_dir/check.json"
  --record "clippy=$output_dir/clippy.json"
  --output "$output_dir/qualification-receipt.json"
)
if [[ "$package" == "codex-hepta-infer-worker-host" ]]; then
  receipt_args+=(--expected-label product-e2e)
  receipt_args+=(--record "product-e2e=$output_dir/product-e2e.json")
fi

set +e
python3 "$repo_root/scripts/inference_worker_command_receipt.py" "${receipt_args[@]}"
receipt_status=$?
set -e
if [[ "$receipt_status" -ne 0 ]]; then
  overall=1
fi

exit "$overall"
