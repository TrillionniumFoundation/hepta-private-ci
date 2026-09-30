#!/usr/bin/env bash
set -euo pipefail

: "${SOURCE_SHA:?}"
: "${SOURCE_TREE:?}"
: "${BASE_SHA:?}"
: "${WORKFLOW_SHA:?}"
: "${GITHUB_RUN_ID:?}"
: "${GITHUB_RUN_ATTEMPT:?}"
: "${RUNNER_IMAGE:?}"
: "${TARGET_TRIPLE:?}"
: "${READINESS_RECORDS:?}"

mkdir -p "$READINESS_RECORDS"/{source,crash,metadata,publication}
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"

receipt() {
  local kind="$1" tested="$2" command="$3" started="$4" finished="$5" code="$6" log="$7" output="$8"
  python3 scripts/kernel_evidence_qualification_receipt.py \
    --kind "$kind" \
    --source-head-sha "$SOURCE_SHA" \
    --source-head-tree "$SOURCE_TREE" \
    --base-sha "$BASE_SHA" \
    --tested-object-sha "$tested" \
    --workflow-sha "$WORKFLOW_SHA" \
    --workflow-run-id "$GITHUB_RUN_ID" \
    --workflow-run-attempt "$GITHUB_RUN_ATTEMPT" \
    --runner-image "$RUNNER_IMAGE" \
    --target-triple "$TARGET_TRIPLE" \
    --command "$command" \
    --started-at-unix-ms "$started" \
    --finished-at-unix-ms "$finished" \
    --exit-code "$code" \
    --log "$log" \
    --output "$output"
}

run_and_receipt() {
  local kind="$1" log="$2" command="$3" output="$4"
  local started finished code
  started="$(date +%s%3N)"
  set +e
  bash -lc "$command" >"$log" 2>&1
  code=$?
  set -e
  finished="$(date +%s%3N)"
  receipt "$kind" "$SOURCE_SHA" "$command" "$started" "$finished" "$code" "$log" "$output"
}

source_command='set -euo pipefail; test "$(git rev-parse HEAD)" = "$SOURCE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli'
run_and_receipt exact_source \
  "$READINESS_RECORDS/source/tests.log" \
  "$source_command" \
  "$READINESS_RECORDS/exact_source.json"

set +e
python3 scripts/kernel_evidence_crash_matrix.py \
  --workspace "$GITHUB_WORKSPACE/codex-rs" \
  --source-head-sha "$SOURCE_SHA" \
  --source-head-tree "$SOURCE_TREE" \
  --base-sha "$BASE_SHA" \
  --workflow-sha "$WORKFLOW_SHA" \
  --workflow-run-id "$GITHUB_RUN_ID" \
  --workflow-run-attempt "$GITHUB_RUN_ATTEMPT" \
  --runner-image "$RUNNER_IMAGE" \
  --target-triple "$TARGET_TRIPLE" \
  --output-directory "$READINESS_RECORDS/crash" \
  --timeout-seconds 300 \
  >"$READINESS_RECORDS/crash/driver.log" 2>&1
set -e

metadata_command='set -euo pipefail; python3 -m unittest scripts.tests.test_kernel_evidence_readiness scripts.tests.test_kernel_evidence_runtime_status scripts.tests.test_kernel_evidence_crash_matrix; python3 scripts/kernel_evidence_status.py verify; python3 scripts/hepta-docs.py verify; python3 scripts/hepta-implementation-maps.py verify'
run_and_receipt metadata \
  "$READINESS_RECORDS/metadata/metadata.log" \
  "$metadata_command" \
  "$READINESS_RECORDS/metadata.json"

publication_command='set -euo pipefail; cd codex-rs; cargo test --locked -p codex-hepta-evidence --lib publication_tests:: -- --nocapture --test-threads=1; cargo test --locked -p codex-hepta-agentd --lib evidence_publication_driver_tests:: -- --nocapture --test-threads=1; cd "$GITHUB_WORKSPACE"; python3 - "$READINESS_RECORDS/crash/SUMMARY.json" <<"PY"
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("schemaVersion") != 2 or value.get("passed") is not True:
    raise SystemExit("crash matrix is not terminal success")
if value.get("scenarioCount") != value.get("requiredScenarioCount"):
    raise SystemExit("crash matrix inventory is incomplete")
PY'
run_and_receipt publication_diagnostics \
  "$READINESS_RECORDS/publication/publication.log" \
  "$publication_command" \
  "$READINESS_RECORDS/publication_diagnostics.json"
