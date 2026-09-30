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

worktree_state() {
  git status --porcelain=v1 --untracked-files=all
}

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
  local kind="$1" log="$2" command="$3" output="$4" timeout_seconds="$5"
  local started finished code before after
  started="$(date +%s%3N)"
  before="$(worktree_state)"
  if [[ -n "$before" ]]; then
    {
      printf 'qualification command refused a dirty pre-execution worktree\n'
      printf '%s\n' "$before"
    } >"$log"
    code=125
  else
    set +e
    timeout --signal=TERM --kill-after=30s "${timeout_seconds}s" \
      bash -lc "$command" >"$log" 2>&1
    code=$?
    set -e
  fi
  after="$(worktree_state)"
  if [[ -n "$after" ]]; then
    {
      printf '\nqualification command dirtied the immutable candidate worktree\n'
      printf '%s\n' "$after"
    } >>"$log"
    code=125
  fi
  finished="$(date +%s%3N)"
  receipt "$kind" "$SOURCE_SHA" "$command" "$started" "$finished" "$code" "$log" "$output"
}

source_command='set -euo pipefail; test "$(git rev-parse HEAD)" = "$SOURCE_SHA"; test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"; cd codex-rs; cargo test --locked -p codex-hepta-evidence; cargo test --locked -p codex-hepta-agentd --lib --test kernel_evidence_product --test kernel_evidence_profile --test kernel_evidence_paging_product --test kernel_evidence_publication_cli'
run_and_receipt exact_source \
  "$READINESS_RECORDS/source/tests.log" \
  "$source_command" \
  "$READINESS_RECORDS/exact_source.json" \
  5400

crash_before="$(worktree_state)"
if [[ -n "$crash_before" ]]; then
  {
    printf 'crash matrix refused a dirty pre-execution worktree\n'
    printf '%s\n' "$crash_before"
  } >"$READINESS_RECORDS/crash/driver.log"
else
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
fi
crash_after="$(worktree_state)"
if [[ -n "$crash_after" ]]; then
  {
    printf '\ncrash matrix dirtied the immutable candidate worktree\n'
    printf '%s\n' "$crash_after"
  } >>"$READINESS_RECORDS/crash/driver.log"
  if [[ -f "$READINESS_RECORDS/crash/SUMMARY.json" ]]; then
    python3 - "$READINESS_RECORDS/crash/SUMMARY.json" "$crash_after" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
value["passed"] = False
value["worktreeDirty"] = True
value["worktreeStatus"] = sys.argv[2]
fd, name = tempfile.mkstemp(dir=path.parent, prefix=".dirty-crash-summary-")
temporary = Path(name)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    temporary.unlink(missing_ok=True)
PY
  fi
fi

metadata_command='set -euo pipefail; bash scripts/kernel_evidence_validate_metadata.sh'
run_and_receipt metadata \
  "$READINESS_RECORDS/metadata/metadata.log" \
  "$metadata_command" \
  "$READINESS_RECORDS/metadata.json" \
  1200

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
  "$READINESS_RECORDS/publication_diagnostics.json" \
  1800
