#!/usr/bin/env bash
set -euo pipefail
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

: "${SOURCE_SHA:?SOURCE_SHA is required}"
root="$(git -C "${GITHUB_WORKSPACE:-.}" rev-parse --show-toplevel)"
test "$(realpath "$root")" = "$(realpath "${GITHUB_WORKSPACE:-.}")"
test "$(git -C "$root" rev-parse HEAD)" = "$SOURCE_SHA"
source_tree="$(git -C "$root" rev-parse HEAD^{tree})"
export SOURCE_TREE="$source_tree"
mkdir -p source-evidence candidate-evidence/bin

for script in qualification/browser-servo/*.mjs; do node --check "$script"; done
npm --prefix apps/hepta-browser run check
mapfile -d '' tests < <(find apps/hepta-browser/test -maxdepth 1 -type f -name '*.test.js' -print0 | sort -z)
test "${#tests[@]}" -ge 20
printf '%s\n' "${tests[@]}" > source-evidence/module-test-inventory.txt

cargo fmt --manifest-path codex-rs/Cargo.toml --package codex-hepta-agentd -- --check
cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd browser_servo --lib \
  2>&1 | tee candidate-evidence/agentd-browser-tests.log
cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser-service 2>&1 | tee candidate-evidence/agentd-service-tests.log
cargo check --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser --bin hepta-agentd-browser-service \
  2>&1 | tee candidate-evidence/agentd-check.log
clippy_messages=candidate-evidence/agentd-clippy.messages.jsonl
clippy_stderr=candidate-evidence/agentd-clippy.stderr.log
set +e
cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd \
  --lib --bin hepta-agentd-browser --bin hepta-agentd-browser-service \
  --no-deps --message-format=json \
  >"$clippy_messages" 2>"$clippy_stderr"
clippy_status=$?
set -e
cat "$clippy_stderr"
node qualification/browser-servo/strict-agentd-clippy.mjs \
  --input "$clippy_messages" --stderr "$clippy_stderr" \
  --cargo-status "$clippy_status" --expected-sha "$SOURCE_SHA" \
  --output candidate-evidence/agentd-clippy-receipt.json
npm --prefix apps/hepta-browser run worker:check \
  2>&1 | tee candidate-evidence/worker-check.log
npm --prefix apps/hepta-browser run worker:test \
  2>&1 | tee candidate-evidence/worker-tests.log
cargo check --manifest-path "$root/codex-rs/Cargo.toml" --locked --workspace --all-targets \
  2>&1 | tee candidate-evidence/full-workspace-check.log

stage="${RUNNER_TEMP:-/tmp}/browser-servo-stage"
rm -rf "$stage"
git -C "$root" worktree add --detach "$stage" "$SOURCE_SHA"
cleanup_stage() {
  git -C "$root" worktree remove --force "$stage" >/dev/null 2>&1 || true
  git -C "$root" worktree prune >/dev/null 2>&1 || true
}
trap cleanup_stage EXIT
node "$stage/qualification/browser-servo/strict-stage-validation.mjs" \
  --root "$stage" --expected-sha "$SOURCE_SHA" --expected-tree "$source_tree" \
  --minimum-tests 20 --execute true \
  --output "$root/source-evidence/staged-workspace.json"
cleanup_stage
trap - EXIT

node qualification/browser-servo/protocol-compatibility.mjs \
  --root "$root" --output source-evidence/protocol-compatibility.json
QUALIFICATION_LANE=exact-head \
EFFECTIVE_SOURCE_SHA="$SOURCE_SHA" \
EFFECTIVE_SOURCE_TREE="$source_tree" \
  node apps/hepta-browser/scripts/qualification-state.mjs \
    --receipt source-evidence/source-receipt.json
printf '%s\n%s\n' "$SOURCE_SHA" "$source_tree" > source-evidence/source.txt
sha256sum source-evidence/*.json > source-evidence/json.sha256

node --test \
  apps/hepta-browser/test/agentd-service.test.js \
  apps/hepta-browser/test/persisted-reconciler.test.js \
  apps/hepta-browser/test/runtime.test.js \
  apps/hepta-browser/test/worker-lifecycle.test.js \
  apps/hepta-browser/test/worker-owner-regression.test.js \
  2>&1 | tee candidate-evidence/product-fault-tests.log

export SOURCE_DATE_EPOCH="$(git -C "$root" show -s --format=%ct HEAD)"
export CARGO_INCREMENTAL=0 LC_ALL=C.UTF-8 TZ=UTC
worker_target="${RUNNER_TEMP:-/tmp}/browser-servo-worker-target"
agentd_target="${RUNNER_TEMP:-/tmp}/browser-servo-agentd-target"
rm -rf "$worker_target" "$agentd_target"
CARGO_TARGET_DIR="$worker_target" cargo build --release --locked \
  --manifest-path apps/hepta-browser/servo-worker/Cargo.toml \
  2>&1 | tee candidate-evidence/worker-build.log
CARGO_TARGET_DIR="$agentd_target" cargo build --release --locked \
  --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  --bin hepta-agentd-browser-service \
  2>&1 | tee candidate-evidence/agentd-build.log
install -m 0555 "$worker_target/release/hepta-servo-worker" candidate-evidence/bin/hepta-servo-worker
install -m 0555 "$agentd_target/release/hepta-agentd-browser-service" candidate-evidence/bin/hepta-agentd-browser-service
sha256sum candidate-evidence/bin/* > candidate-evidence/candidate.sha256

node qualification/browser-servo/protocol-compatibility.mjs \
  --root "$root" --output candidate-evidence/protocol-compatibility.json
node qualification/browser-servo/candidate-manifest.mjs \
  --root "$root" \
  --worker candidate-evidence/bin/hepta-servo-worker \
  --agentd candidate-evidence/bin/hepta-agentd-browser-service \
  --protocol candidate-evidence/protocol-compatibility.json \
  --expected-sha "$SOURCE_SHA" --expected-tree "$source_tree" \
  --output candidate-evidence/candidate-manifest.json

worker=candidate-evidence/bin/hepta-servo-worker
node apps/hepta-browser/scripts/real-worker-smoke.js "$worker" \
  | tee candidate-evidence/real-worker-smoke.json
node apps/hepta-browser/scripts/real-browser-e2e.js "$worker" \
  | tee candidate-evidence/real-browser-e2e.json
node apps/hepta-browser/scripts/real-browser-soak.js "$worker" \
  | tee candidate-evidence/real-browser-soak.json
BROWSER_SERVO_FAULT_SUITE_PASSED=true \
  node qualification/browser-servo/product-fault-probe.mjs \
    --agentd candidate-evidence/bin/hepta-agentd-browser-service \
    --worker candidate-evidence/bin/hepta-servo-worker \
    --timeout-ms 10000 --output candidate-evidence/product-fault-probe.json

test "$(git -C "$root" rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git -C "$root" rev-parse HEAD^{tree})" = "$source_tree"
git -C "$root" diff --check
git -C "$root" diff --exit-code
test -z "$(git -C "$root" status --porcelain --untracked-files=no)"
