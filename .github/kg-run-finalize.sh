#!/usr/bin/env bash
set -euo pipefail

platform="${1:?platform is required}"
expected_runner="${2:-}"
branch="work/kg-abc-evidence-hardening-20260928"
root="$(git rev-parse --show-toplevel)"
cd "$root"

if [[ -n "$expected_runner" ]]; then
  test "$RUNNER_NAME" = "$expected_runner"
fi
test "$GITHUB_EVENT_NAME" = "push"
test "$GITHUB_REF_NAME" = "$branch"
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
git diff --quiet
git diff --cached --quiet

case "$platform" in
  linux)
    test "$RUNNER_OS" = "Linux"
    sudo apt-get update
    sudo apt-get install -y build-essential bubblewrap libcap-dev pkg-config protobuf-compiler
    command -v protoc
    protoc --version
    sudo sysctl -w kernel.unprivileged_userns_clone=1
    if sysctl kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
      sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    fi
    ;;
  macos)
    test "$RUNNER_OS" = "macOS"
    if ! command -v protoc >/dev/null 2>&1; then
      brew install protobuf
    fi
    command -v protoc
    protoc --version
    ;;
  *)
    printf 'unsupported platform: %s\n' "$platform" >&2
    exit 2
    ;;
esac

# Keep the decoded finalizer inside the checkout: its source-location-derived
# ROOT must resolve to this repository, not to RUNNER_TEMP's parent directory.
python3 - <<'PY'
import base64
import gzip
from pathlib import Path
source = Path('.github/kg-finalize.py.gz.b64')
target = Path('.github/kg-finalize.py')
target.write_bytes(gzip.decompress(base64.b64decode(source.read_bytes())))
PY
python3 .github/kg-finalize.py
python3 scripts/hepta_kg_status.py --apply
(
  cd codex-rs
  cargo fmt --all
)

CODEX_REPO_ROOT="$root" PYTHONPATH=scripts python3 scripts/hepta_ci_v8.py

(
  cd codex-rs
  cargo test --locked -p codex-hepta-kg -- --nocapture
  cargo test --locked -p codex-hepta-prompt-optimizer -- --nocapture
  cargo test --locked -p codex-hepta-memory --lib cognitive_kg_oracle_tests:: -- --nocapture --test-threads=1
  if [[ "$platform" == linux ]]; then
    cargo test --locked -p codex-hepta-agentd --test cognitive_product_e2e -- --nocapture --test-threads=1
  else
    cargo check --locked -p codex-hepta-agentd --all-targets
  fi
  cargo clippy --locked \
    -p codex-hepta-kg -p codex-hepta-prompt-optimizer \
    -p codex-hepta-memory -p codex-hepta-agentd \
    --no-deps --all-targets -- -D warnings
)

git config user.name "Hepta Knowledge Graph Bot"
git config user.email "hepta-kg-bot@users.noreply.github.com"
rm -f .github/kg-finalize.py.gz.b64
rm -f .github/kg-finalize.py
rm -f .github/kg-close.py.gz
rm -f .github/kg-run-finalize.sh
rm -f .github/workflows/hepta-kg-finalize.yml
rm -f .github/workflows/hepta-kg-remaining-four-closure.yml
git add -A
git diff --cached --check
git commit -m "feat(knowledge.graph): wire guarded product resource contracts"

python3 scripts/hepta-implementation-maps.py migrate --module knowledge.graph
python3 scripts/hepta_kg_status.py --apply
git add \
  docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json \
  docs/modules/knowledge.graph/CURRENT_STATUS.json \
  docs/modules/knowledge.graph/CURRENT_STATUS.md \
  docs/modules/knowledge.graph/TECHNICAL.md
git diff --cached --check
git commit -m "docs(knowledge.graph): bind split status to closure candidate"

python3 scripts/hepta_knowledge_graph_map_verify.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --expected-tree "$(git rev-parse HEAD^{tree})"
python3 scripts/hepta_kg_status.py --check
python3 scripts/hepta_kg_documentation_sync.py --check
git diff --quiet
git diff --cached --quiet
test -z "$(git status --porcelain --untracked-files=no)"

git fetch origin "$branch"
test "$(git rev-parse "origin/$branch")" = "$GITHUB_SHA"
git push origin "HEAD:refs/heads/$branch"
