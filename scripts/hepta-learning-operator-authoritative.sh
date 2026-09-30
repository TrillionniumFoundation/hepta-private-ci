#!/usr/bin/env bash
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

SOURCE_SHA="${SOURCE_SHA:-$(git rev-parse HEAD)}"
SOURCE_TREE="$(git rev-parse "${SOURCE_SHA}^{tree}")"
FROZEN_SOURCE_SHA="${FROZEN_SOURCE_SHA:-${SOURCE_SHA}}"
OBSERVATION_HEAD_SHA="${OBSERVATION_HEAD_SHA:-${SOURCE_SHA}}"
BASE_SHA="${BASE_SHA:-}"
if [[ -z "${BASE_SHA}" ]] || ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  git fetch --no-tags origin main
  BASE_SHA="$(git rev-parse origin/main)"
fi
if [[ "${BASE_SHA}" == "${SOURCE_SHA}" ]]; then
  BASE_SHA="$(git rev-parse "${SOURCE_SHA}^1")"
fi

EVIDENCE=".hepta-evidence/learning-operator"
STAGES="${EVIDENCE}/stages"
GATES="${EVIDENCE}/gates"
rm -rf "${EVIDENCE}"
mkdir -p "${STAGES}" "${GATES}"
TARGET="$(rustc -vV | awk '/^host:/ {print $2}')"
ZERO_SHA="0000000000000000000000000000000000000000"
SYNTHETIC_SHA="${ZERO_SHA}"
SYNTHETIC_TREE="${ZERO_SHA}"
export SOURCE_SHA SOURCE_TREE FROZEN_SOURCE_SHA OBSERVATION_HEAD_SHA BASE_SHA TARGET

record_stage() {
  local stage="$1"
  local status="$2"
  local reason="$3"
  local command="$4"
  local log="$5"
  local code="${6:-}"
  local code_args=()
  if [[ -n "${code}" ]]; then
    code_args=(--exit-code "${code}")
  fi
  python3 scripts/hepta-learning-operator-stage.py record \
    --stage "${stage}" \
    --source-sha "${SOURCE_SHA}" \
    --source-tree "${SOURCE_TREE}" \
    --workflow-run-id "${GITHUB_RUN_ID:-local}" \
    --run-attempt "${GITHUB_RUN_ATTEMPT:-1}" \
    --status "${status}" \
    --reason "${reason}" \
    --command "${command}" \
    --log "${log}" \
    "${code_args[@]}" \
    --output "${STAGES}/${stage}.json"
}

run_stage() {
  local stage="$1"
  local log="$2"
  local description="$3"
  shift 3
  mkdir -p "$(dirname "${log}")"
  local execution_command
  printf -v execution_command '%q ' "$@"
  set +e
  {
    printf 'stage=%s\npurpose=%s\ncommand:' "${stage}" "${description}"
    printf ' %q' "$@"
    printf '\n'
    "$@"
  } 2>&1 | tee "${log}"
  local pipeline_status=("${PIPESTATUS[@]}")
  local rc="${pipeline_status[0]}"
  if [[ "${pipeline_status[1]}" -ne 0 ]]; then
    rc="${pipeline_status[1]}"
  fi
  set -u
  if [[ "${rc}" -eq 0 ]]; then
    record_stage "${stage}" passed "" "${execution_command}" "${log}" "${rc}"
  else
    record_stage "${stage}" failed "command exited ${rc}" "${execution_command}" "${log}" "${rc}"
  fi
  return 0
}

stage_passed() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
raise SystemExit(0 if path.is_file() and json.loads(path.read_text()).get("status") == "passed" else 1)
PY
}

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
stages = [
    "source_identity",
    "documentation_schema",
    "default_api_surface",
    "compile",
    "unit_tests",
    "product_integration",
    "mutation",
    "coverage",
    "resource_performance",
    "static_quality",
    "deterministic_merge",
    "exact_source_receipt",
]
commands = {
    "source_identity": "bind exact source SHA/tree and clean checkout",
    "documentation_schema": "verify canonical STATUS, documents, schema and exact-source implementation projection",
    "default_api_surface": "compile independent default pass/fail and feature compatibility consumers",
    "compile": "cargo check all targets and build the operator for the rustc host",
    "unit_tests": "operator tests, lifecycle state-space and payload replay rejection",
    "product_integration": "fresh-process load plus ledger/evaluation/selection/ranker/revocation/rollback E2E",
    "mutation": "executed source mutation suite",
    "coverage": "source-bound llvm coverage threshold",
    "resource_performance": "bounded sensor and tabular regression performance matrix",
    "static_quality": "strict clippy and formatting",
    "deterministic_merge": "ordered-parent synthetic merge contract, compile, tests and product E2E",
    "exact_source_receipt": "source-bound qualification manifest and readiness inputs",
}
Path('.hepta-evidence/learning-operator/test-set.json').write_text(
    json.dumps(
        {
            'schema': 'hepta.learning-operator.test-set.v2',
            'schemaVersion': 2,
            'stages': stages,
            'commands': commands,
            'nonPassedStatuses': ['failed', 'not_run'],
        },
        indent=2,
        sort_keys=True,
    ) + '\n',
    encoding='utf-8',
)
PY

run_stage source_identity "${EVIDENCE}/source-identity.log" \
  "bind exact source SHA/tree and clean checkout" \
  bash -lc '
    set -euo pipefail
    test "$(git rev-parse HEAD)" = "${SOURCE_SHA}"
    test "$(git rev-parse HEAD^{tree})" = "${SOURCE_TREE}"
    test "$(git rev-parse "${SOURCE_SHA}^{tree}")" = "${SOURCE_TREE}"
    git diff --check
    git diff --exit-code
    test -z "$(git status --porcelain --untracked-files=no)"
    printf "sourceSha=%s\nsourceTree=%s\nbaseSha=%s\n" "${SOURCE_SHA}" "${SOURCE_TREE}" "${BASE_SHA}"
  '

run_stage documentation_schema "${EVIDENCE}/documentation-schema.log" \
  "canonical status/document/schema and exact-source implementation projection" \
  bash -lc '
    set -euo pipefail
    python3 scripts/hepta-learning-operator-map.py emit \
      --source-sha "${SOURCE_SHA}" \
      --source-tree "${SOURCE_TREE}" \
      --output ".hepta-evidence/learning-operator/implementation-map.json"
    python3 scripts/hepta-learning-operator-map.py verify \
      --path ".hepta-evidence/learning-operator/implementation-map.json" \
      --expected-sha "${SOURCE_SHA}" \
      --expected-tree "${SOURCE_TREE}"
    python3 scripts/hepta-learning-operator-contract.py verify
    python3 scripts/test_hepta_lane_e_closure.py
    python3 scripts/test_hepta_learning_operator_evidence.py
  '

run_stage default_api_surface "${EVIDENCE}/default-api-surface.log" \
  "independent consumer default pass/fail and feature compatibility compilation" \
  python3 scripts/hepta-learning-operator-api-surface.py \
    --output "${EVIDENCE}/api-surface.json"

run_stage compile "${EVIDENCE}/compile.log" \
  "workspace all-target check and host-target operator build" \
  bash -lc '
    set -euo pipefail
    cargo check --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-learning-ledger \
      -p codex-hepta-bellman-operator \
      -p codex-hepta-agentd --all-targets
    cargo build --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-bellman-operator --target "${TARGET}"
  '

run_stage unit_tests "${EVIDENCE}/unit-tests.log" \
  "operator, lifecycle, semantic sensor receipt and payload replay tests" \
  bash -lc '
    set -euo pipefail
    just test --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input --lib
    just test --locked \
      -p codex-hepta-agentd --lib learning_operator_coordinator::tests \
      --test-threads=1
    just test --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input \
      mutation_persisted_payload_cannot_reuse_the_selected_pin \
      --test-threads=1
  '

run_stage product_integration "${EVIDENCE}/product-integration.log" \
  "fresh-process selected load and real protocol shadow E2E" \
  bash -lc '
    set -euo pipefail
    just test --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input \
      distinct_process_load_changes_prediction_and_rolls_back_without_retraining \
      --test-threads=1
    just test --locked \
      -p codex-hepta-agentd --lib \
      evaluated_load_uses_real_owner_training_selection_revocation_and_rollback \
      --test-threads=1
  '

run_stage mutation "${EVIDENCE}/mutation.log" \
  "executed fail-closed source mutation suite" \
  python3 scripts/hepta-learning-operator-mutation.py \
    --output "${EVIDENCE}/mutation.json"

run_stage coverage "${EVIDENCE}/coverage.log" \
  "operator source-bound llvm line coverage threshold" \
  bash -lc '
    set -euo pipefail
    cargo llvm-cov --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input --lib \
      --fail-under-lines 70 --json \
      --output-path "${ROOT}/.hepta-evidence/learning-operator/coverage.json"
  '

run_stage resource_performance "${EVIDENCE}/resource-performance.log" \
  "sensor and tabular regression time/RSS/estimated-memory matrix" \
  bash -lc '
    set -euo pipefail
    just test --locked --release \
      -p codex-hepta-bellman-operator \
      authoritative_performance_matrix_v1 \
      --profile learning-operator-performance --run-ignored only --test-threads=1 --success-output immediate
  '

run_stage static_quality "${EVIDENCE}/static-quality.log" \
  "strict clippy, formatting and source hygiene" \
  bash -lc '
    set -euo pipefail
    cargo clippy --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input --all-targets -- -D warnings
    cargo clippy --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-agentd --lib -- -D warnings
    cargo fmt --manifest-path codex-rs/Cargo.toml \
      --package codex-hepta-learning-ledger \
      --package codex-hepta-bellman-operator \
      --package codex-hepta-agentd -- --check
    git diff --check
  '

SYNTH_DIR="${RUNNER_TEMP:-/tmp}/learning-operator-synthetic-${GITHUB_RUN_ID:-local}"
rm -rf "${SYNTH_DIR}"
set +e
git worktree add --detach "${SYNTH_DIR}" "${BASE_SHA}" >/dev/null 2>&1
WORKTREE_RC=$?
set -u
if [[ "${WORKTREE_RC}" -ne 0 ]]; then
  : > "${EVIDENCE}/deterministic-merge.log"
  record_stage deterministic_merge failed "unable to create deterministic merge worktree" \
    "ordered-parent synthetic merge qualification" "${EVIDENCE}/deterministic-merge.log" "${WORKTREE_RC}"
else
  (
    set -euo pipefail
    cd "${SYNTH_DIR}"
    git -c user.name=hepta-learning-operator-ci \
      -c user.email=hepta-learning-operator-ci@users.noreply.github.com \
      merge --no-commit --no-ff "${SOURCE_SHA}"
    SYNTHETIC_TREE_LOCAL="$(git write-tree)"
    SYNTHETIC_SHA_LOCAL="$(printf "%s\n" "learning.operator deterministic synthetic merge" | \
      GIT_AUTHOR_DATE="2000-01-01T00:00:00Z" \
      GIT_COMMITTER_DATE="2000-01-01T00:00:00Z" \
      git -c user.name=hepta-learning-operator-ci \
        -c user.email=hepta-learning-operator-ci@users.noreply.github.com \
        commit-tree "${SYNTHETIC_TREE_LOCAL}" -p "${BASE_SHA}" -p "${SOURCE_SHA}")"
    test "$(git rev-parse "${SYNTHETIC_SHA_LOCAL}^1")" = "${BASE_SHA}"
    test "$(git rev-parse "${SYNTHETIC_SHA_LOCAL}^2")" = "${SOURCE_SHA}"
    git reset --hard "${SYNTHETIC_SHA_LOCAL}"
    python3 scripts/hepta-learning-operator-contract.py verify
    python3 scripts/hepta-learning-operator-api-surface.py \
      --output ".hepta-evidence/learning-operator-synthetic-api.json"
    cargo check --manifest-path codex-rs/Cargo.toml --locked \
      -p codex-hepta-learning-ledger \
      -p codex-hepta-bellman-operator \
      -p codex-hepta-agentd --all-targets
    just test --locked \
      -p codex-hepta-bellman-operator --features qualification-unverified-input --lib
    just test --locked \
      -p codex-hepta-agentd --lib learning_operator_coordinator::tests \
      --test-threads=1
    just test --locked \
      -p codex-hepta-agentd --lib \
      evaluated_load_uses_real_owner_training_selection_revocation_and_rollback \
      --test-threads=1
    printf "SYNTHETIC_SHA=%s\nSYNTHETIC_TREE=%s\n" \
      "${SYNTHETIC_SHA_LOCAL}" "${SYNTHETIC_TREE_LOCAL}" \
      > "${ROOT}/${EVIDENCE}/synthetic.env"
  ) 2>&1 | tee "${EVIDENCE}/deterministic-merge.log"
  SYNTH_PIPELINE_STATUS=("${PIPESTATUS[@]}")
  SYNTH_RC="${SYNTH_PIPELINE_STATUS[0]}"
  if [[ "${SYNTH_PIPELINE_STATUS[1]}" -ne 0 ]]; then
    SYNTH_RC="${SYNTH_PIPELINE_STATUS[1]}"
  fi
  if [[ "${SYNTH_RC}" -eq 0 ]]; then
    # shellcheck disable=SC1090
    source "${EVIDENCE}/synthetic.env"
    record_stage deterministic_merge passed "" \
      "ordered-parent synthetic merge qualification" "${EVIDENCE}/deterministic-merge.log" "${SYNTH_RC}"
  else
    record_stage deterministic_merge failed "synthetic merge qualification exited ${SYNTH_RC}" \
      "ordered-parent synthetic merge qualification" "${EVIDENCE}/deterministic-merge.log" "${SYNTH_RC}"
  fi
  git worktree remove --force "${SYNTH_DIR}" >/dev/null 2>&1 || true
fi

emit_gate() {
  local name="$1"
  local stage="$2"
  local command="$3"
  local log="$4"
  python3 scripts/hepta-learning-operator-evidence.py \
    --name "${name}" \
    --source-sha "${SOURCE_SHA}" \
    --source-tree "${SOURCE_TREE}" \
    --command "${command}" \
    --log "${log}" \
    --status-file "${STAGES}/${stage}.json" \
    --target "${TARGET}" \
    --output "${GATES}/${name}.json"
}

emit_gate exact-head source_identity "bind exact source SHA/tree and clean checkout" "${EVIDENCE}/source-identity.log"
emit_gate documentation-map documentation_schema "verify canonical status/schema and exact-source map" "${EVIDENCE}/documentation-schema.log"
emit_gate default-api-surface default_api_surface "independent API consumer compile pass/fail" "${EVIDENCE}/default-api-surface.log"
emit_gate workspace-all-targets compile "cargo check owner/operator/Agentd all targets" "${EVIDENCE}/compile.log"
emit_gate target-build compile "cargo build operator for rustc host target" "${EVIDENCE}/compile.log"
emit_gate module-tests unit_tests "operator all-feature library tests" "${EVIDENCE}/unit-tests.log"
emit_gate lifecycle-state-space unit_tests "Agentd shadow lifecycle tests" "${EVIDENCE}/unit-tests.log"
emit_gate payload-replay unit_tests "persisted payload mutation/replay rejection" "${EVIDENCE}/unit-tests.log"
emit_gate fresh-process-load product_integration "fresh-process selected load and rollback" "${EVIDENCE}/product-integration.log"
emit_gate product-shadow-e2e product_integration "ledger/evaluation/selection/ranker/revocation/rollback E2E" "${EVIDENCE}/product-integration.log"
emit_gate mutation-profile mutation "executed source mutation suite" "${EVIDENCE}/mutation.log"
emit_gate coverage coverage "source-bound line coverage threshold" "${EVIDENCE}/coverage.log"
emit_gate performance-profile resource_performance "regression time and memory matrix" "${EVIDENCE}/resource-performance.log"
emit_gate static-quality static_quality "strict clippy and formatting" "${EVIDENCE}/static-quality.log"
emit_gate synthetic-merge deterministic_merge "deterministic ordered-parent merge qualification" "${EVIDENCE}/deterministic-merge.log"

PRE_RECEIPT_STAGES="source_identity,documentation_schema,default_api_surface,compile,unit_tests,product_integration,mutation,coverage,resource_performance,static_quality,deterministic_merge"
if python3 scripts/hepta-learning-operator-stage.py verify \
  --directory "${STAGES}" --required "${PRE_RECEIPT_STAGES}"; then
  WORKFLOW_PATH="${QUALIFICATION_WORKFLOW_PATH:-.github/workflows/learning-operator-authoritative.yml}"
  WORKFLOW_BLOB="$(git rev-parse "${SOURCE_SHA}:${WORKFLOW_PATH}")"
  EVIDENCE_ARGS=()
  for path in "${GATES}"/*.json; do
    name="$(basename "${path}" .json)"
    EVIDENCE_ARGS+=(--evidence "${name}=${path}")
  done
  set +e
  {
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
  } 2>&1 | tee "${EVIDENCE}/exact-source-receipt.log"
  RECEIPT_PIPELINE_STATUS=("${PIPESTATUS[@]}")
  RECEIPT_RC="${RECEIPT_PIPELINE_STATUS[0]}"
  if [[ "${RECEIPT_PIPELINE_STATUS[1]}" -ne 0 ]]; then
    RECEIPT_RC="${RECEIPT_PIPELINE_STATUS[1]}"
  fi
  set -u
  if [[ "${RECEIPT_RC}" -eq 0 ]]; then
    record_stage exact_source_receipt passed "" \
      "emit and verify exact-source qualification manifest" "${EVIDENCE}/exact-source-receipt.log" "${RECEIPT_RC}"
  else
    record_stage exact_source_receipt failed "qualification receipt exited ${RECEIPT_RC}" \
      "emit and verify exact-source qualification manifest" "${EVIDENCE}/exact-source-receipt.log" "${RECEIPT_RC}"
  fi
else
  printf 'receipt not run because prerequisite stages are non-passing\n' \
    > "${EVIDENCE}/exact-source-receipt.log"
  record_stage exact_source_receipt not_run "prerequisite stage failed or was not run" \
    "emit and verify exact-source qualification manifest" "${EVIDENCE}/exact-source-receipt.log"
fi

WORKFLOW_PATH="${QUALIFICATION_WORKFLOW_PATH:-.github/workflows/learning-operator-authoritative.yml}"
WORKFLOW_BLOB="$(git rev-parse "${SOURCE_SHA}:${WORKFLOW_PATH}" 2>/dev/null || printf '%s' "${ZERO_SHA}")"
GITHUB_MERGE_SHA="${GITHUB_SHA:-${SOURCE_SHA}}"
if [[ ! "${GITHUB_MERGE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  GITHUB_MERGE_SHA="${SOURCE_SHA}"
fi
IMPLEMENTATION_MAP_FILE="${EVIDENCE}/implementation-map.json"
if [[ ! -f "${IMPLEMENTATION_MAP_FILE}" ]]; then
  IMPLEMENTATION_MAP_FILE="docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
fi
RUNNER_IMAGE="${ImageOS:-unknown}:${ImageVersion:-unknown}:${RUNNER_NAME:-unknown}"
python3 scripts/hepta-learning-operator-readiness.py emit \
  --source-head-sha "${SOURCE_SHA}" \
  --frozen-source-sha "${FROZEN_SOURCE_SHA}" \
  --observation-head-sha "${OBSERVATION_HEAD_SHA}" \
  --source-tree-hash "${SOURCE_TREE}" \
  --base-sha "${BASE_SHA}" \
  --deterministic-merge-sha "${SYNTHETIC_SHA}" \
  --github-merge-sha "${GITHUB_MERGE_SHA}" \
  --workflow-sha "${WORKFLOW_BLOB}" \
  --workflow-path "${WORKFLOW_PATH}" \
  --workflow-run-id "${GITHUB_RUN_ID:-local}" \
  --attempt-id "${GITHUB_RUN_ATTEMPT:-1}" \
  --runner-image "${RUNNER_IMAGE}" \
  --target-triple "${TARGET}" \
  --toolchain-file "${EVIDENCE}/rustc.txt" \
  --test-set-file "${EVIDENCE}/test-set.json" \
  --implementation-map "${IMPLEMENTATION_MAP_FILE}" \
  --stage-directory "${STAGES}" \
  --output "${EVIDENCE}/readiness-manifest.json"
python3 scripts/hepta-learning-operator-readiness.py verify \
  --path "${EVIDENCE}/readiness-manifest.json"

if [[ -f "${EVIDENCE}/qualification-manifest.json" ]]; then
  python3 scripts/hepta-learning-operator-contract.py verify \
    --receipt "${EVIDENCE}/qualification-manifest.json"
  CONTRACT_RC=$?
  if [[ "${CONTRACT_RC}" -ne 0 ]]; then
    record_stage exact_source_receipt failed "final contract/readiness verification failed" \
      "emit and verify exact-source qualification manifest" "${EVIDENCE}/exact-source-receipt.log" "${CONTRACT_RC}"
    python3 scripts/hepta-learning-operator-readiness.py emit \
      --source-head-sha "${SOURCE_SHA}" \
      --frozen-source-sha "${FROZEN_SOURCE_SHA}" \
      --observation-head-sha "${OBSERVATION_HEAD_SHA}" \
      --source-tree-hash "${SOURCE_TREE}" \
      --base-sha "${BASE_SHA}" \
      --deterministic-merge-sha "${SYNTHETIC_SHA}" \
      --github-merge-sha "${GITHUB_MERGE_SHA}" \
      --workflow-sha "${WORKFLOW_BLOB}" \
      --workflow-path "${WORKFLOW_PATH}" \
      --workflow-run-id "${GITHUB_RUN_ID:-local}" \
      --attempt-id "${GITHUB_RUN_ATTEMPT:-1}" \
      --runner-image "${RUNNER_IMAGE}" \
      --target-triple "${TARGET}" \
      --toolchain-file "${EVIDENCE}/rustc.txt" \
      --test-set-file "${EVIDENCE}/test-set.json" \
      --implementation-map "${IMPLEMENTATION_MAP_FILE}" \
      --stage-directory "${STAGES}" \
      --output "${EVIDENCE}/readiness-manifest.json"
  fi
fi

REQUIRED_STAGES="${PRE_RECEIPT_STAGES},exact_source_receipt"
if python3 scripts/hepta-learning-operator-stage.py verify \
  --directory "${STAGES}" --required "${REQUIRED_STAGES}" \
  && python3 scripts/hepta-learning-operator-readiness.py verify \
    --path "${EVIDENCE}/readiness-manifest.json" --require-qualified; then
  printf 'learning.operator engineering qualification passed for %s\n' "${SOURCE_SHA}"
  exit 0
fi
printf 'learning.operator qualification failed; inspect %s/readiness-manifest.json\n' "${EVIDENCE}" >&2
exit 1
