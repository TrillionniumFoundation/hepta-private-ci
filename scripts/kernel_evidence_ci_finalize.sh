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

common=(
  --source-head-sha "$SOURCE_SHA"
  --source-head-tree "$SOURCE_TREE"
  --base-sha "$BASE_SHA"
  --deterministic-merge-sha "${MERGE_SHA:-}"
  --github-synthetic-merge-sha "${GITHUB_SYNTHETIC_SHA:-}"
  --workflow-sha "$WORKFLOW_SHA"
  --final-merge-sha "${FINAL_MERGE_SHA:-}"
  --workflow-run-id "$GITHUB_RUN_ID"
  --workflow-run-attempt "$GITHUB_RUN_ATTEMPT"
  --runner-image "$RUNNER_IMAGE"
  --target-triple "$TARGET_TRIPLE"
)
receipts=(
  --qualification-receipt "exact_source=$READINESS_RECORDS/exact_source.json"
  --qualification-receipt "deterministic_merge=$READINESS_RECORDS/deterministic_merge.json"
  --qualification-receipt "metadata=$READINESS_RECORDS/metadata.json"
  --qualification-receipt "publication_diagnostics=$READINESS_RECORDS/publication_diagnostics.json"
)

# Receipt metadata is not trusted until it is rebound to the retained bytes.
# The audit always emits a diagnostic object; a non-zero result is converted
# into fail-closed final readiness rather than losing the evidence artifact.
set +e
python3 scripts/kernel_evidence_receipt_audit.py \
  --records-root "$READINESS_RECORDS" \
  "${common[@]}" \
  --output "$READINESS_RECORDS/RECEIPT_AUDIT.json" \
  >"$READINESS_RECORDS/receipt-audit.log" 2>&1
receipt_audit_code=$?
set -e
printf 'receipt_audit_exit_code=%s\n' "$receipt_audit_code" \
  >>"$READINESS_RECORDS/receipt-audit.log"

python3 scripts/kernel_evidence_runtime_status.py \
  "${common[@]}" \
  --checked-in-status-source qualification/kernel-evidence/STATUS_SOURCE.json \
  "${receipts[@]}" \
  --crash-summary "$READINESS_RECORDS/crash/SUMMARY.json" \
  --output "$READINESS_RECORDS/STATUS_SOURCE.json"

map_path=docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json
current_map="$READINESS_RECORDS/metadata/IMPLEMENTATION_MAP.current.json"
original_map="$READINESS_RECORDS/metadata/IMPLEMENTATION_MAP.checked-in.json"
map_overlaid=false
restore_map() {
  if [[ "$map_overlaid" == true && -f "$original_map" ]]; then
    cp "$original_map" "$map_path"
    map_overlaid=false
  fi
}
trap restore_map EXIT
if [[ -s "$current_map" ]]; then
  cp "$map_path" "$original_map"
  cp "$current_map" "$map_path"
  map_overlaid=true
fi

python3 scripts/kernel_evidence_readiness.py \
  --root "$GITHUB_WORKSPACE" \
  "${common[@]}" \
  --runtime-status-source "$READINESS_RECORDS/STATUS_SOURCE.json" \
  --checked-in-status-source qualification/kernel-evidence/STATUS_SOURCE.json \
  "${receipts[@]}" \
  --artifact "source_log=$READINESS_RECORDS/source/tests.log" \
  --artifact "merge_log=$READINESS_RECORDS/merge/tests.log" \
  --artifact "metadata_log=$READINESS_RECORDS/metadata/metadata.log" \
  --artifact "implementation_map_current=$current_map" \
  --artifact "implementation_map_binding=$READINESS_RECORDS/metadata/implementation-map-binding.txt" \
  --artifact "merge_metadata_log=$READINESS_RECORDS/merge-metadata/metadata/metadata.log" \
  --artifact "merge_implementation_map_current=$READINESS_RECORDS/merge-metadata/metadata/IMPLEMENTATION_MAP.current.json" \
  --artifact "merge_implementation_map_binding=$READINESS_RECORDS/merge-metadata/metadata/implementation-map-binding.txt" \
  --artifact "publication_log=$READINESS_RECORDS/publication/publication.log" \
  --artifact "crash_summary=$READINESS_RECORDS/crash/SUMMARY.json" \
  --artifact "receipt_audit=$READINESS_RECORDS/RECEIPT_AUDIT.json" \
  --artifact "receipt_audit_log=$READINESS_RECORDS/receipt-audit.log" \
  --artifact "runtime_status=$READINESS_RECORDS/STATUS_SOURCE.json" \
  --crash-receipts "$READINESS_RECORDS/crash" \
  --output "$READINESS_RECORDS/READINESS_MANIFEST.preliminary.json"

restore_map
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
test -z "$(git status --porcelain=v1 --untracked-files=all)"

python3 scripts/kernel_evidence_finalize_readiness.py \
  --preliminary-manifest "$READINESS_RECORDS/READINESS_MANIFEST.preliminary.json" \
  --runtime-status "$READINESS_RECORDS/STATUS_SOURCE.json" \
  --receipt-audit "$READINESS_RECORDS/RECEIPT_AUDIT.json" \
  --output "$READINESS_RECORDS/READINESS_MANIFEST.json"

python3 - "$READINESS_RECORDS/READINESS_MANIFEST.json" "${IS_MAIN:-false}" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
readiness = value["readiness"]
required = (
    "repository_controlled_ready",
    "local_integrity_ready",
    "authenticated_frontier_protocol_ready",
    "crash_matrix_ready",
    "runtime_status_exact",
    "artifact_inventory_ready",
    "receipt_audit_qualified",
    "exact_source_qualified",
    "deterministic_merge_qualified",
    "metadata_qualified",
    "publication_diagnostics_qualified",
)
missing = [name for name in required if readiness.get(name) is not True]
if missing:
    raise SystemExit("readiness failed closed: " + ", ".join(missing))
if sys.argv[2] == "true" and readiness.get("final_merge_requalified") is not True:
    raise SystemExit("real main merge SHA was not requalified")
forbidden = (
    "authenticated_frontier_authority_ready",
    "external_rollback_anchor_ready",
    "independent_acceptance",
    "operator_activation",
    "production_activation",
    "promotion_approved",
    "release_approved",
)
assert not [name for name in forbidden if readiness.get(name) is True]
PY
