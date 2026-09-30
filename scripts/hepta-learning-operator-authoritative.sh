#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

SOURCE_SHA="${SOURCE_SHA:-$(git rev-parse HEAD)}"
if [[ "$(git rev-parse HEAD)" != "${SOURCE_SHA}" ]]; then
  echo "checked out source does not equal SOURCE_SHA" >&2
  exit 1
fi
SOURCE_TREE="$(git rev-parse "${SOURCE_SHA}^{tree}")"
BASE_SHA="${BASE_SHA:-}"
if [[ -z "${BASE_SHA}" ]] || ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  git fetch --no-tags origin main
  BASE_SHA="$(git rev-parse origin/main)"
fi
if [[ "${BASE_SHA}" == "${SOURCE_SHA}" ]]; then
  BASE_SHA="$(git rev-parse "${SOURCE_SHA}^1")"
fi

EVIDENCE=".hepta-evidence/learning-operator"
rm -rf "${EVIDENCE}"
mkdir -p "${EVIDENCE}/gates"
TARGET="$(rustc -vV | awk '/^host:/ {print $2}')"
export SOURCE_SHA SOURCE_TREE BASE_SHA TARGET

run_log() {
  local log="$1"
  shift
  {
    printf 'command:'
    printf ' %q' "$@"
    printf '\n'
    "$@"
  } 2>&1 | tee "${log}"
}

{
  printf 'sourceSha=%s\nsourceTree=%s\nbaseSha=%s\n' \
    "${SOURCE_SHA}" "${SOURCE_TREE}" "${BASE_SHA}"
  test "$(git rev-parse HEAD)" = "${SOURCE_SHA}"
  test "$(git rev-parse HEAD^{tree})" = "${SOURCE_TREE}"
  git diff --check
  git diff --exit-code
} 2>&1 | tee "${EVIDENCE}/exact-head.log"

rustc -vV > "${EVIDENCE}/rustc.txt"
{
  printf 'runnerOs=%s\nrunnerArch=%s\nrunnerName=%s\n' \
    "${RUNNER_OS:-unknown}" "${RUNNER_ARCH:-unknown}" "${RUNNER_NAME:-unknown}"
  printf 'imageOs=%s\nimageVersion=%s\n' \
    "${ImageOS:-unknown}" "${ImageVersion:-unknown}"
  uname -a
  if [[ -f /etc/os-release ]]; then
    cat /etc/os-release
  fi
} > "${EVIDENCE}/runner.txt"

python3 - <<'PY'
import json
from pathlib import Path
commands = [
    "python3 scripts/hepta-learning-operator-contract.py verify",
    "cargo check --locked -p codex-hepta-learning-ledger -p codex-hepta-bellman-operator -p codex-hepta-agentd --all-targets",
    "cargo build --locked -p codex-hepta-bellman-operator --target <rustc-host>",
    "cargo test --locked -p codex-hepta-bellman-operator --all-features --lib",
    "cargo test --locked -p codex-hepta-agentd --lib learning_operator_coordinator::tests",
    "cargo test --locked -p codex-hepta-bellman-operator --all-features distinct_process_load_changes_prediction_and_rolls_back_without_retraining",
    "cargo test --locked -p codex-hepta-agentd --lib evaluated_load_uses_real_owner_training_selection_revocation_and_rollback",
    "cargo llvm-cov --locked -p codex-hepta-bellman-operator --all-features --lib --fail-under-lines 70",
    "python3 scripts/hepta-learning-operator-mutation.py",
    "cargo test --release -p codex-hepta-bellman-operator authoritative_performance_matrix_v1 -- --ignored",
    "cargo clippy --locked -p codex-hepta-bellman-operator --all-features --all-targets -- -D warnings",
    "cargo clippy --locked -p codex-hepta-agentd --lib -- -D warnings",
    "deterministic ordered-parent synthetic merge + contract/check/test/product-E2E",
]
Path('.hepta-evidence/learning-operator/test-set.json').write_text(
    json.dumps({'schema': 'hepta.learning-operator.test-set.v1', 'commands': commands}, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)
PY

{
  python3 scripts/hepta-learning-operator-contract.py verify
  python3 scripts/hepta-learning-operator-map.py emit \
    --source-sha "${SOURCE_SHA}" \
    --source-tree "${SOURCE_TREE}" \
    --output "${EVIDENCE}/implementation-map.json"
  python3 scripts/hepta-learning-operator-map.py verify \
    --path "${EVIDENCE}/implementation-map.json" \
    --expected-sha "${SOURCE_SHA}" \
    --expected-tree "${SOURCE_TREE}"
} 2>&1 | tee "${EVIDENCE}/documentation-map.log"

run_log "${EVIDENCE}/workspace-all-targets.log" \
  cargo check --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-learning-ledger \
    -p codex-hepta-bellman-operator \
    -p codex-hepta-agentd \
    --all-targets

run_log "${EVIDENCE}/target-build.log" \
  cargo build --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --target "${TARGET}"

run_log "${EVIDENCE}/module-tests.log" \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features --lib

run_log "${EVIDENCE}/lifecycle-state-space.log" \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-agentd --lib learning_operator_coordinator::tests \
    -- --test-threads=1

run_log "${EVIDENCE}/fresh-process-load.log" \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features \
    distinct_process_load_changes_prediction_and_rolls_back_without_retraining \
    -- --test-threads=1

run_log "${EVIDENCE}/product-shadow-e2e.log" \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-agentd --lib \
    evaluated_load_uses_real_owner_training_selection_revocation_and_rollback \
    -- --test-threads=1

run_log "${EVIDENCE}/payload-replay.log" \
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features \
    mutation_persisted_payload_cannot_reuse_the_selected_pin \
    -- --test-threads=1

{
  cargo llvm-cov --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features --lib \
    --fail-under-lines 70 --json \
    --output-path "${ROOT}/${EVIDENCE}/coverage.json"
} 2>&1 | tee "${EVIDENCE}/coverage.log"

run_log "${EVIDENCE}/mutation-profile.log" \
  python3 scripts/hepta-learning-operator-mutation.py \
    --output "${EVIDENCE}/mutation.json"

{
  cargo test --manifest-path codex-rs/Cargo.toml --locked --release \
    -p codex-hepta-bellman-operator \
    authoritative_performance_matrix_v1 \
    -- --ignored --nocapture --test-threads=1
} 2>&1 | tee "${EVIDENCE}/performance-profile.log"

{
  cargo clippy --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features --all-targets -- -D warnings
  cargo clippy --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-agentd --lib -- -D warnings
  cargo fmt --manifest-path codex-rs/Cargo.toml \
    --package codex-hepta-learning-ledger \
    --package codex-hepta-bellman-operator \
    --package codex-hepta-agentd -- --check
} 2>&1 | tee "${EVIDENCE}/static-quality.log"

SYNTH_DIR="${RUNNER_TEMP:-/tmp}/learning-operator-synthetic-${GITHUB_RUN_ID:-local}"
rm -rf "${SYNTH_DIR}"
git worktree add --detach "${SYNTH_DIR}" "${BASE_SHA}"
cleanup() {
  git worktree remove --force "${SYNTH_DIR}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

(
  set -euo pipefail
  cd "${SYNTH_DIR}"
  git -c user.name=hepta-learning-operator-ci \
    -c user.email=hepta-learning-operator-ci@users.noreply.github.com \
    merge --no-commit --no-ff "${SOURCE_SHA}"
  SYNTHETIC_TREE="$(git write-tree)"
  SYNTHETIC_SHA="$(printf '%s\n' 'learning.operator deterministic synthetic merge' | \
    GIT_AUTHOR_DATE='2000-01-01T00:00:00Z' \
    GIT_COMMITTER_DATE='2000-01-01T00:00:00Z' \
    git -c user.name=hepta-learning-operator-ci \
      -c user.email=hepta-learning-operator-ci@users.noreply.github.com \
      commit-tree "${SYNTHETIC_TREE}" -p "${BASE_SHA}" -p "${SOURCE_SHA}")"
  test "$(git rev-parse "${SYNTHETIC_SHA}^1")" = "${BASE_SHA}"
  test "$(git rev-parse "${SYNTHETIC_SHA}^2")" = "${SOURCE_SHA}"
  test "$(git rev-parse "${SYNTHETIC_SHA}^{tree}")" = "${SYNTHETIC_TREE}"
  git reset --hard "${SYNTHETIC_SHA}"
  python3 scripts/hepta-learning-operator-contract.py verify
  cargo check --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-learning-ledger \
    -p codex-hepta-bellman-operator \
    -p codex-hepta-agentd --all-targets
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features --lib
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-agentd --lib learning_operator_coordinator::tests \
    -- --test-threads=1
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-bellman-operator --all-features \
    distinct_process_load_changes_prediction_and_rolls_back_without_retraining \
    -- --test-threads=1
  cargo test --manifest-path codex-rs/Cargo.toml --locked \
    -p codex-hepta-agentd --lib \
    evaluated_load_uses_real_owner_training_selection_revocation_and_rollback \
    -- --test-threads=1
  printf 'SYNTHETIC_SHA=%s\nSYNTHETIC_TREE=%s\n' \
    "${SYNTHETIC_SHA}" "${SYNTHETIC_TREE}" \
    > "${ROOT}/${EVIDENCE}/synthetic.env"
) 2>&1 | tee "${EVIDENCE}/synthetic-merge.log"
# shellcheck disable=SC1090
source "${EVIDENCE}/synthetic.env"
cleanup
trap - EXIT

emit_gate() {
  local name="$1"
  local command="$2"
  local log="$3"
  python3 scripts/hepta-learning-operator-evidence.py \
    --name "${name}" \
    --source-sha "${SOURCE_SHA}" \
    --source-tree "${SOURCE_TREE}" \
    --command "${command}" \
    --log "${log}" \
    --target "${TARGET}" \
    --output "${EVIDENCE}/gates/${name}.json"
}

emit_gate exact-head "bind exact source SHA/tree and clean checkout" "${EVIDENCE}/exact-head.log"
emit_gate documentation-map "verify contract and generate exact source-object map" "${EVIDENCE}/documentation-map.log"
emit_gate workspace-all-targets "cargo check owner/operator/Agentd all targets" "${EVIDENCE}/workspace-all-targets.log"
emit_gate target-build "cargo build operator for rustc host target" "${EVIDENCE}/target-build.log"
emit_gate module-tests "operator all-feature library tests" "${EVIDENCE}/module-tests.log"
emit_gate lifecycle-state-space "Agentd shadow-only lifecycle state-space tests" "${EVIDENCE}/lifecycle-state-space.log"
emit_gate fresh-process-load "independent-process selected load and rollback without retraining" "${EVIDENCE}/fresh-process-load.log"
emit_gate product-shadow-e2e "real ledger evaluation selection artifact ranker revocation rollback chain" "${EVIDENCE}/product-shadow-e2e.log"
emit_gate payload-replay "opaque persisted payload mutation/replay rejection" "${EVIDENCE}/payload-replay.log"
emit_gate coverage "operator source-bound line coverage threshold" "${EVIDENCE}/coverage.log"
emit_gate mutation-profile "executed fail-closed source mutation suite" "${EVIDENCE}/mutation-profile.log"
emit_gate performance-profile "1K-16K sensor and 100K-1M tabular time and memory qualification matrix" "${EVIDENCE}/performance-profile.log"
emit_gate static-quality "strict clippy, formatting, and source hygiene" "${EVIDENCE}/static-quality.log"
emit_gate synthetic-merge "deterministic ordered-parent synthetic merge compile tests and product E2E" "${EVIDENCE}/synthetic-merge.log"

WORKFLOW_PATH="${QUALIFICATION_WORKFLOW_PATH:-.github/workflows/learning-operator-authoritative.yml}"
WORKFLOW_BLOB="$(git rev-parse "${SOURCE_SHA}:${WORKFLOW_PATH}")"
EVIDENCE_ARGS=()
for path in "${EVIDENCE}"/gates/*.json; do
  name="$(basename "${path}" .json)"
  EVIDENCE_ARGS+=(--evidence "${name}=${path}")
done
python3 scripts/hepta-learning-operator-receipt.py emit \
  --source-sha "${SOURCE_SHA}" \
  --source-tree "${SOURCE_TREE}" \
  --workflow-path "${WORKFLOW_PATH}" \
  --workflow-blob "${WORKFLOW_BLOB}" \
  --workflow-run-id "${GITHUB_RUN_ID:-local}" \
  --workflow-run-attempt "${GITHUB_RUN_ATTEMPT:-1}" \
  --main-sha "${BASE_SHA}" \
  --synthetic-sha "${SYNTHETIC_SHA}" \
  --synthetic-tree "${SYNTHETIC_TREE}" \
  --target "${TARGET}" \
  --rustc-file "${EVIDENCE}/rustc.txt" \
  --runner-file "${EVIDENCE}/runner.txt" \
  --test-set-file "${EVIDENCE}/test-set.json" \
  --implementation-map "${EVIDENCE}/implementation-map.json" \
  "${EVIDENCE_ARGS[@]}" \
  --output "${EVIDENCE}/qualification-manifest.json"
python3 scripts/hepta-learning-operator-receipt.py verify \
  --path "${EVIDENCE}/qualification-manifest.json" \
  --expected-source-sha "${SOURCE_SHA}" \
  --expected-source-tree "${SOURCE_TREE}"
python3 scripts/hepta-learning-operator-contract.py verify \
  --receipt "${EVIDENCE}/qualification-manifest.json"

git diff --check
git diff --exit-code
test -z "$(git status --porcelain --untracked-files=no)"
printf 'learning.operator authoritative qualification passed for %s\n' "${SOURCE_SHA}"
