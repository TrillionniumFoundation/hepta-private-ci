#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JSON_OUT="${ROOT}/.hepta-evidence/learning-eval/faults.json"
LOG_OUT="${ROOT}/.hepta-evidence/learning-eval/faults.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON_OUT="$2"
      shift 2
      ;;
    --log)
      LOG_OUT="$2"
      shift 2
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "${JSON_OUT}")" "$(dirname "${LOG_OUT}")"
: >"${LOG_OUT}"

cases=(
  consumer_binding_is_integrity_bound_and_authority_free
  accepted_unknown_is_reconciled_without_duplicate_publish
  conflicting_semantics_are_never_overwritten
  consumed_then_terminal_is_replayable_and_exact_retry_is_idempotent
  terminal_without_consumption_and_conflicting_terminal_fail_closed
  truncated_frame_and_second_writer_are_rejected
  newer_generation_fences_out_the_old_writer
  indeterminate_write_poison_requires_recovery_and_preserves_history
  locked_file_store_replays_takeover_and_rejects_backup_rollback
  child_process_observes_lock_then_recovers_after_owner_exit
  compaction_drops_obsolete_fences_and_preserves_final_anchor
)

cd "${ROOT}/codex-rs"
for case_name in "${cases[@]}"; do
  {
    printf 'BEGIN case=%s\n' "${case_name}"
    just test --locked \
      -p codex-hepta-intelligence-eval \
      "${case_name}" \
      --test-threads=1
    printf 'PASS case=%s\n' "${case_name}"
  } 2>&1 | tee -a "${LOG_OUT}"
done

log_sha="$(sha256sum "${LOG_OUT}" | awk '{print $1}')"
cat >"${JSON_OUT}" <<JSON
{
  "schema": "hepta.learning-eval.fault-matrix.v1",
  "caseCount": ${#cases[@]},
  "passed": ${#cases[@]},
  "failed": 0,
  "logSha256": "${log_sha}",
  "cases": [
$(printf '    "%s",\n' "${cases[@]}" | sed '$ s/,$//')
  ]
}
JSON

python3 - "${JSON_OUT}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
assert value["schema"] == "hepta.learning-eval.fault-matrix.v1"
assert value["caseCount"] == value["passed"] == len(value["cases"])
assert value["failed"] == 0
assert len(value["logSha256"]) == 64
print(json.dumps({"status": "ok", "faultCases": value["caseCount"]}, sort_keys=True))
PY
