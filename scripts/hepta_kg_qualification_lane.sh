#!/usr/bin/env bash
# Run every knowledge.graph qualification check, preserve per-check logs, and
# return failure only after the full lane has produced an auditable receipt.
set -uo pipefail

REPO_ROOT="${1:-$(pwd)}"
LANE="${KG_QUALIFICATION_LANE:?KG_QUALIFICATION_LANE must be set}"
EVIDENCE_DIR="${KG_EVIDENCE_DIR:-${RUNNER_TEMP:-/tmp}/knowledge-graph-${LANE}}"
RESULTS_TSV="${EVIDENCE_DIR}/results.tsv"
mkdir -p "${EVIDENCE_DIR}"
: >"${RESULTS_TSV}"

failures=0

record_result() {
  local name="$1"
  local status="$2"
  local required="$3"
  local detail="$4"
  printf '%s\t%s\t%s\t%s\n' "${name}" "${status}" "${required}" "${detail}" >>"${RESULTS_TSV}"
  if [[ "${required}" == "true" && "${status}" != "passed" ]]; then
    failures=$((failures + 1))
  fi
}

run_check() {
  local name="$1"
  shift
  local log="${EVIDENCE_DIR}/${name}.log"
  printf '::group::knowledge.graph check %s\n' "${name}"
  set +e
  (
    cd "${REPO_ROOT}/codex-rs"
    "$@"
  ) > >(tee "${log}") 2>&1
  local status=$?
  set -e
  printf '::endgroup::\n'
  if [[ ${status} -eq 0 ]]; then
    record_result "${name}" "passed" "true" "exit=0"
  else
    record_result "${name}" "failed" "true" "exit=${status}"
  fi
}

run_optional_check() {
  local name="$1"
  local required_path="$2"
  shift 2
  if [[ -e "${REPO_ROOT}/${required_path}" ]]; then
    run_check "${name}" "$@"
  else
    record_result "${name}" "not_applicable" "false" "missing_on_${LANE}:${required_path}"
  fi
}

# Core deterministic kernel, external query contract and public operation metrics.
run_check kg_kernel cargo test --locked -p codex-hepta-kg -- --nocapture
run_optional_check kg_query_acceptance \
  codex-rs/hepta-kg/tests/query_acceptance.rs \
  cargo test --locked -p codex-hepta-kg --test query_acceptance -- --nocapture
run_optional_check kg_query_resource_contract \
  codex-rs/hepta-kg/tests/query_resource_contract.rs \
  cargo test --locked -p codex-hepta-kg --test query_resource_contract -- --nocapture
run_optional_check kg_operation_measurement \
  codex-rs/hepta-kg/tests/operation_measurement.rs \
  cargo test --locked -p codex-hepta-kg --test operation_measurement -- \
    --exact public_operation_boundaries_emit_nonzero_regression_metrics --nocapture

# Prompt source, projection and bounded real consumer.
run_check prompt_registry cargo test --locked -p codex-hepta-prompt-registry -- --nocapture
run_check prompt_optimizer cargo test --locked -p codex-hepta-prompt-optimizer -- --nocapture

# Durable owner, property suite, delivery consistency and destructive recovery.
run_check cognitive_kg_owner \
  cargo test --locked -p codex-hepta-memory --lib -- --nocapture --test-threads=1
run_check cognitive_kg_properties \
  cargo test --locked -p codex-hepta-memory --lib cognitive_kg_property_tests:: \
    -- --nocapture --test-threads=1
run_optional_check kg_delivery_consistency \
  codex-rs/hepta-memory/tests/kg_delivery_consistency.rs \
  cargo test --locked -p codex-hepta-memory --test kg_delivery_consistency -- \
    --nocapture --test-threads=1
run_check kg_crash_recovery \
  cargo test --locked -p codex-hepta-memory --lib \
    cognitive_store_tests::qualification_kg_projection_crash_windows_restore_exact_predecessor \
    -- --ignored --exact --nocapture --test-threads=1
run_check kg_history_reopen \
  cargo test --locked -p codex-hepta-memory --lib \
    cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection \
    -- --ignored --exact --nocapture --test-threads=1

# Exact authoring head owns the expensive capacity receipt. Other lanes retain
# the same functional checks without pretending to issue that receipt.
if [[ "${LANE}" == "source-head" ]]; then
  run_check kg_capacity_receipt \
    cargo test --locked -p codex-hepta-memory --lib \
      cognitive_kg_benchmark_tests::qualification_knowledge_graph_capacity_receipt \
      -- --ignored --exact --nocapture --test-threads=1
else
  record_result kg_capacity_receipt not_applicable false "source-head-only"
fi

# Actual Agentd product path and qualification witness.
run_optional_check agentd_product_path \
  codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs \
  cargo test --locked -p codex-hepta-agentd --test cognitive_product_e2e -- \
    --nocapture --test-threads=1
run_optional_check agentd_qualification_witness \
  codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs \
  cargo test --locked -p codex-hepta-agentd --features qualification-cognitive-write \
    --test cognitive_product_e2e -- --nocapture --test-threads=1

# Lint after execution so a lint failure cannot erase runtime evidence.
run_check strict_kg_lint \
  cargo clippy --locked \
    -p codex-hepta-kg -p codex-hepta-prompt-registry \
    -p codex-hepta-prompt-optimizer -p codex-hepta-memory -p codex-hepta-agentd \
    --no-deps --all-targets --features codex-hepta-agentd/qualification-cognitive-write \
    -- -D warnings

export HEPTA_KG_RECEIPT_REPO_ROOT="${REPO_ROOT}"
export HEPTA_KG_RECEIPT_LANE="${LANE}"
export HEPTA_KG_RECEIPT_RESULTS="${RESULTS_TSV}"
export HEPTA_KG_RECEIPT_DIR="${EVIDENCE_DIR}"
export HEPTA_KG_RECEIPT_FAILURES="${failures}"
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
from datetime import datetime, timezone

root = pathlib.Path(os.environ["HEPTA_KG_RECEIPT_REPO_ROOT"])
lane = os.environ["HEPTA_KG_RECEIPT_LANE"]
results_path = pathlib.Path(os.environ["HEPTA_KG_RECEIPT_RESULTS"])
evidence_dir = pathlib.Path(os.environ["HEPTA_KG_RECEIPT_DIR"])
failures = int(os.environ["HEPTA_KG_RECEIPT_FAILURES"])

def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()

def file_digest(relative: str) -> str | None:
    path = root / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

results = []
for line in results_path.read_text(encoding="utf-8").splitlines():
    name, status, required, detail = line.split("\t", 3)
    results.append(
        {
            "name": name,
            "status": status,
            "required": required == "true",
            "detail": detail,
        }
    )

logs = []
for path in sorted(evidence_dir.glob("*.log")):
    logs.append(
        {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    )

receipt = {
    "schema": "hepta.knowledge-graph.qualification-receipt.v1",
    "lane": lane,
    "candidateLane": lane in {"source-head", "base-merge"},
    "testedCommit": git("rev-parse", "HEAD"),
    "testedTree": git("rev-parse", "HEAD^{tree}"),
    "sourceCommit": os.environ.get("SOURCE_SHA"),
    "baseCommit": os.environ.get("BASE_SHA"),
    "workflowBlob": (
        git("rev-parse", "HEAD:.github/workflows/hepta-knowledge-graph-qualification.yml")
        if (root / ".github/workflows/hepta-knowledge-graph-qualification.yml").is_file()
        else None
    ),
    "cargoLockSha256": file_digest("codex-rs/Cargo.lock"),
    "kgSchemaSha256": file_digest(
        "codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql"
    ),
    "implementationMapSha256": file_digest(
        "docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json"
    ),
    "results": results,
    "logs": logs,
    "requiredFailureCount": failures,
    "allRequiredPassed": failures == 0,
    "operatorAcceptance": "not_accepted",
    "activation": False,
    "release": False,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
}
payload = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
(evidence_dir / "receipt.json").write_text(payload, encoding="utf-8")
(evidence_dir / "receipt.sha256").write_text(
    hashlib.sha256(payload.encode("utf-8")).hexdigest() + "  receipt.json\n",
    encoding="utf-8",
)
print(payload)
PY

if [[ ${failures} -ne 0 ]]; then
  printf 'knowledge.graph lane %s completed with %s required failure(s)\n' \
    "${LANE}" "${failures}" >&2
  exit 1
fi
