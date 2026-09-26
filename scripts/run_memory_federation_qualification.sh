#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Verify only maps whose declared source/evidence is changed by this closure.
# Repository-wide map truth remains enforced by the protected global CI lane.
python3 scripts/hepta-implementation-maps.py migrate \
  --module memory.federation \
  --module knowledge.graph
git diff --exit-code -- \
  docs/modules/memory.federation/IMPLEMENTATION_MAP.json \
  docs/modules/knowledge.graph/IMPLEMENTATION_MAP.json

cd codex-rs
cargo fmt \
  -p codex-hepta-memory-federation \
  -p codex-hepta-memory \
  -p codex-hepta-memory-extension \
  -p codex-hepta-agentd \
  -p codex-app-server -- --check

cargo test -p codex-hepta-memory-federation --lib
cargo test -p codex-hepta-memory-federation --lib --features legacy-v1
cargo test -p codex-hepta-memory --lib cognitive_runtime_tests
cargo test -p codex-hepta-memory --lib cognitive_federation_tests
cargo test -p codex-hepta-memory-extension --lib cognitive::federation
cargo check -p codex-hepta-agentd -p codex-app-server

cargo clippy \
  -p codex-hepta-memory-federation \
  -p codex-hepta-memory \
  -p codex-hepta-memory-extension \
  -p codex-app-server \
  --all-targets -- -D warnings
cargo clippy -p codex-hepta-memory-federation --all-targets --features legacy-v1 -- -D warnings
cargo clippy -p codex-hepta-agentd --lib -- -D warnings

cd "$ROOT"
git diff --check
test -z "$(git status --porcelain --untracked-files=no)"
