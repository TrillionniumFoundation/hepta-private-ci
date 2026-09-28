#!/usr/bin/env bash
set -euo pipefail

python3 scripts/kernel_authority_direct_repair.py
(
  cd codex-rs
  cargo +1.95.0 fmt --all
)
git diff --check

git config user.name 'kernel-authority-repair[bot]'
git config user.email 'kernel-authority-repair[bot]@users.noreply.github.com'
git add \
  CALLERS.toml \
  codex-rs/hepta-contracts \
  codex-rs/hepta-automation/tests/automation.rs \
  codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs
if git diff --cached --quiet; then
  echo 'reviewed source repair produced no source changes' >&2
  exit 1
fi
git commit -m 'fix(kernel-authority): close recovery and qualification gaps'
SOURCE_COMMIT="$(git rev-parse HEAD)"
SOURCE_TREE="$(git rev-parse 'HEAD^{tree}')"
export SOURCE_COMMIT SOURCE_TREE

python3 scripts/hepta-implementation-maps.py migrate \
  --module automation.taskflow \
  --module cognitive.read \
  --module control.engineering \
  --module intelligence.control \
  --module kernel.authority \
  --module kernel.operations \
  --module knowledge.graph \
  --module learning.artifacts \
  --module learning.ledger \
  --module learning.operator \
  --module learning.plasticity \
  --module memory.federation \
  --module memory.retrieval \
  --module objective.compiler \
  --module platform.types \
  --module prompt.registry \
  --module runtime.agentd \
  --module runtime.fleet \
  --module runtime.supervisor \
  --module utility.ndu
python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path('qualification/kernel-authority/status_manifest.json')
value = json.loads(path.read_text(encoding='utf-8'))
value['sourceAnchor'] = {
    'commit': os.environ['SOURCE_COMMIT'],
    'tree': os.environ['SOURCE_TREE'],
}
path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
PY
python3 scripts/kernel_authority_status.py write
python3 scripts/hepta-implementation-maps.py sync-plasticity-status
rm -f \
  .github/workflows/kernel-authority-direct-repair.yml \
  .github/workflows/kernel-authority-direct-repair-v2.yml \
  .github/workflows/kernel-authority-direct-repair-v3.yml \
  .github/workflows/kernel-authority-one-shot-repair.yml \
  scripts/kernel_authority_direct_repair.py \
  scripts/kernel_authority_direct_repair_v3.sh
git diff --check

git add -A
if git diff --cached --quiet; then
  echo 'projection regeneration produced no staged changes' >&2
  exit 1
fi
git commit -m 'docs(kernel-authority): regenerate candidate-bound truth'
PROJECTION_COMMIT="$(git rev-parse HEAD)"
PROJECTION_TREE="$(git rev-parse 'HEAD^{tree}')"
printf 'source_commit=%s\nsource_tree=%s\nprojection_commit=%s\nprojection_tree=%s\n' \
  "$SOURCE_COMMIT" "$SOURCE_TREE" "$PROJECTION_COMMIT" "$PROJECTION_TREE"

python3 scripts/kernel_authority_status.py check
python3 qualification/kernel-authority/generate_status.py --check
python3 scripts/verify_hepta_callers.py
python3 scripts/hepta-implementation-maps.py verify \
  --expected-sha "$SOURCE_COMMIT" \
  --expected-tree "$SOURCE_TREE"
python3 qualification/kernel-authority/verify.py self-test
python3 -m unittest discover -s qualification/kernel-authority -p 'test_*.py' -v
python3 qa/b4-no-bypass/test_kernel_authority_closed_world.py -v
git diff --check
test -z "$(git status --porcelain)"

export CARGO_BUILD_JOBS=2
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_TEST_DEBUG=0
export CARGO_INCREMENTAL=0
(
  cd codex-rs
  cargo +1.95.0 fmt --all -- --check
  cargo +1.95.0 test --package codex-hepta-contracts --locked
  cargo +1.95.0 clippy --package codex-hepta-contracts --all-targets --locked -- -D warnings
  cargo +1.95.0 test --package codex-hepta-automation --test automation --locked \
    v1_store_migrates_atomically_to_dispatch_outcome_schema -- --exact
  cargo +1.95.0 test --package codex-hepta-agentd --test cognitive_store_product_writer --locked \
    agentd_product_host_recovers_exact_cut_into_fenced_writer_generation -- --exact
)

git push origin HEAD:work/kernel-authority-convergence-20260925

for workflow in \
  rust-ci.yml \
  kernel-authority-convergence.yml \
  kernel-authority-production-closure.yml \
  kernel-authority-status.yml
do
  response="$(mktemp)"
  code="$(curl --silent --show-error --location \
    --output "$response" --write-out '%{http_code}' \
    --request POST \
    --header 'Accept: application/vnd.github+json' \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow}/dispatches" \
    --data '{"ref":"work/kernel-authority-convergence-20260925"}')"
  if [[ "$code" != '204' ]]; then
    echo "workflow dispatch failed for ${workflow}: HTTP ${code}" >&2
    cat "$response" >&2
    exit 1
  fi
done
