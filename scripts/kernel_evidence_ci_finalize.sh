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

python3 scripts/kernel_evidence_runtime_status.py \
  "${common[@]}" \
  --checked-in-status-source qualification/kernel-evidence/STATUS_SOURCE.json \
  "${receipts[@]}" \
  --crash-summary "$READINESS_RECORDS/crash/SUMMARY.json" \
  --output "$READINESS_RECORDS/STATUS_SOURCE.json"

python3 scripts/kernel_evidence_readiness.py \
  --root "$GITHUB_WORKSPACE" \
  "${common[@]}" \
  --runtime-status-source "$READINESS_RECORDS/STATUS_SOURCE.json" \
  --checked-in-status-source qualification/kernel-evidence/STATUS_SOURCE.json \
  "${receipts[@]}" \
  --artifact "source_log=$READINESS_RECORDS/source/tests.log" \
  --artifact "merge_log=$READINESS_RECORDS/merge/tests.log" \
  --artifact "metadata_log=$READINESS_RECORDS/metadata/metadata.log" \
  --artifact "publication_log=$READINESS_RECORDS/publication/publication.log" \
  --artifact "crash_summary=$READINESS_RECORDS/crash/SUMMARY.json" \
  --crash-receipts "$READINESS_RECORDS/crash" \
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
