#!/usr/bin/env bash
set -euo pipefail

branch="ci/automation-taskflow-schema22-finalize-20260929"
trigger_sha="${GITHUB_SHA:?GITHUB_SHA is required}"

test "$(git rev-parse HEAD)" = "$trigger_sha"
remote="$(git ls-remote origin "refs/heads/$branch" | awk '{print $1}')"
test "$remote" = "$trigger_sha"

git config user.name "hepta-automation-convergence"
git config user.email "hepta-automation-convergence@users.noreply.github.com"

# Apply the reviewed source-correctness / bounded-startup patch.
python3 - <<'PY'
import base64
import gzip
from pathlib import Path
source = Path('scripts/automation_taskflow_source_last_mile_20260929.py.gz.b64')
target = Path('scripts/.automation_taskflow_source_last_mile_20260929.py')
target.write_bytes(gzip.decompress(base64.b64decode(source.read_bytes())))
PY
python3 -m py_compile scripts/.automation_taskflow_source_last_mile_20260929.py
python3 scripts/.automation_taskflow_source_last_mile_20260929.py
rm -f scripts/.automation_taskflow_source_last_mile_20260929.py
git diff --check
git add \
  codex-rs/hepta-automation/src/durable_neural_circuit.rs \
  codex-rs/hepta-automation/src/taskflow.rs \
  codex-rs/hepta-automation/tests/durable_neural_circuit.rs \
  codex-rs/hepta-automation/tests/taskflow.rs
git commit --no-verify -m "fix(automation): close circuit replay and bounded startup gaps"

# Repair exact failures from the immutable 18ce focused receipt.
python3 -m py_compile scripts/automation_taskflow_ci_remediation_20260929.py
python3 scripts/automation_taskflow_ci_remediation_20260929.py
(
  cd codex-rs
  cargo check -p codex-hepta-authbus
  cargo fmt \
    -p codex-hepta-operations \
    -p codex-hepta-automation \
    -p codex-hepta-agentd \
    -p codex-hepta-authbus
)
git diff --check
git add \
  codex-rs/Cargo.lock \
  codex-rs/hepta-authbus/Cargo.toml \
  codex-rs/hepta-authbus/src/authority_schema.rs \
  codex-rs/hepta-authbus/src/authority_store.rs \
  codex-rs/hepta-authbus/src/quota_store.rs \
  codex-rs/hepta-authbus/src/trust_store.rs \
  codex-rs/hepta-operations/BUILD.bazel \
  codex-rs/hepta-automation/src/cross_host_recovery.rs \
  codex-rs/hepta-automation/src/durable_neural_circuit.rs \
  codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs \
  codex-rs/hepta-automation/src/external_host_fence.rs \
  codex-rs/hepta-automation/src/lifecycle_bounded.rs \
  codex-rs/hepta-automation/src/neural_circuit_runtime/runtime.rs \
  codex-rs/hepta-automation/tests/automation.rs \
  codex-rs/hepta-automation/tests/durable_neural_circuit.rs \
  codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs \
  codex-rs/hepta-automation/tests/selected_host_profile.rs
git commit --no-verify -m "fix(automation): repair exact native qualification blockers"

# Update schema-22 truth without converting source presence into execution proof.
python3 -m py_compile \
  scripts/automation_taskflow_truthful_finalize_20260929.py \
  scripts/automation_taskflow_layered_contract_20260929.py \
  scripts/automation_taskflow_contract.py \
  scripts/automation_taskflow_selected_host.py
python3 scripts/automation_taskflow_truthful_finalize_20260929.py
python3 scripts/automation_taskflow_layered_contract_20260929.py
python3 scripts/automation_taskflow_contract.py render
python3 scripts/hepta_transition_lineage.py
python3 scripts/hepta-document-index.py

git rm -r \
  .github/workflows/automation-taskflow-converge-20260927.yml \
  .github/workflows/automation-taskflow-converge-selected-host-20260929.yml \
  scripts/automation_taskflow_converge_20260927.py \
  scripts/automation_taskflow_finalize_20260928.py \
  scripts/automation_taskflow_truthful_finalize_20260929.py \
  scripts/automation_taskflow_layered_contract_20260929.py \
  scripts/automation_taskflow_ci_remediation_20260929.py \
  scripts/automation_taskflow_source_last_mile_20260929.py.gz.b64 \
  scripts/automation_taskflow_selected_host_finalize_20260929.sh \
  scripts/automation_taskflow_patch_parts

git diff --check
git add -u
while IFS= read -r -d '' path; do
  git add -- "$path"
done < <(git ls-files --others --exclude-standard -z)
for generated in \
  docs/generated/TRANSITION_STATE_GRAPH.json \
  docs/generated/TRANSITION_STATE_REPORT.md \
  docs/generated/DOCUMENT_INDEX.md \
  docs/generated/DOCUMENT_INDEX.json
do
  test -f "$generated"
  git add -f -- "$generated"
done
git commit --no-verify -m "docs(automation): align schema-22 layered source truth"

# Refresh all module maps affected by the qualification repair.
python3 scripts/hepta-implementation-maps.py migrate --module automation.taskflow
python3 scripts/hepta-implementation-maps.py migrate --module auth.authbus
python3 scripts/hepta-implementation-maps.py migrate --module kernel.operations
git diff --check
if ! git diff --quiet; then
  git add \
    docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json \
    docs/modules/auth.authbus/IMPLEMENTATION_MAP.json \
    docs/modules/kernel.operations/IMPLEMENTATION_MAP.json
  git commit -m "docs(automation): refresh affected implementation navigation"
fi

python3 scripts/automation_taskflow_contract.py observe
python3 scripts/automation_taskflow_contract.py render
python3 scripts/hepta_transition_lineage.py
python3 scripts/hepta-document-index.py
git diff --check
if ! git diff --quiet; then
  git add -u
  while IFS= read -r -d '' path; do
    git add -- "$path"
  done < <(git ls-files --others --exclude-standard -z)
  for generated in \
    docs/generated/TRANSITION_STATE_GRAPH.json \
    docs/generated/TRANSITION_STATE_REPORT.md \
    docs/generated/DOCUMENT_INDEX.md \
    docs/generated/DOCUMENT_INDEX.json
  do
    test -f "$generated"
    git add -f -- "$generated"
  done
  git commit -m "docs(automation): bind exact schema-22 source objects"
fi

candidate_sha="$(git rev-parse HEAD)"
candidate_tree="$(git rev-parse HEAD^{tree})"
python3 scripts/automation_taskflow_contract.py self-test
python3 -m unittest -v \
  scripts/test_automation_taskflow_contract.py \
  scripts/test_verify_automation_taskflow_acceptance.py \
  scripts/test_automation_recovery_sweeps.py \
  scripts/test_automation_taskflow_checkpoint.py \
  scripts/test_automation_taskflow_commands.py \
  scripts/test_automation_taskflow_selected_host.py
python3 scripts/hepta-implementation-maps.py verify \
  --expected-sha "$candidate_sha" \
  --expected-tree "$candidate_tree"
python3 scripts/hepta-module-docs.py verify
python3 scripts/hepta-design-provenance.py verify
python3 scripts/hepta-transition-state.py verify

(
  cd codex-rs
  cargo fmt \
    -p codex-hepta-operations \
    -p codex-hepta-automation \
    -p codex-hepta-agentd \
    -p codex-hepta-authbus \
    -- --check
  cargo check --locked \
    -p codex-hepta-operations \
    -p codex-hepta-automation \
    -p codex-hepta-agentd \
    --all-targets
  cargo clippy --locked \
    -p codex-hepta-automation \
    -p codex-hepta-agentd \
    --all-targets --all-features -- -D warnings
  cargo test --locked -p codex-hepta-authbus
  cargo test --locked -p codex-hepta-automation
  cargo test --locked -p codex-hepta-agentd --lib
)

bazel test --test_output=errors \
  //codex-rs/hepta-automation:hepta-automation-taskflow-kernel-qualification-test \
  //codex-rs/hepta-automation:hepta-automation-taskflow-step-qualification-test

git diff --exit-code
git diff --cached --exit-code
test -z "$(git status --porcelain --untracked-files=no)"

git fetch origin "$branch"
test "$(git rev-parse FETCH_HEAD)" = "$trigger_sha"
git push origin "HEAD:$branch"
