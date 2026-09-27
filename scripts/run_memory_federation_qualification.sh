#!/usr/bin/env bash
set -euxo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Qualification is read-only and pinned twice: before any compiler/test command
# and after the complete matrix.  The implementation-map check deliberately
# reuses the canonical strict verifier while narrowing its registry view to this
# module, so unrelated module provenance cannot contaminate this module receipt.
CANDIDATE_SHA="$(git rev-parse HEAD)"
CANDIDATE_TREE="$(git rev-parse HEAD^{tree})"
GUARD_DIR="$(mktemp -d "${RUNNER_TEMP:-/tmp}/memory-federation-guard.XXXXXX")"
GUARD_STATE="$GUARD_DIR/execution-guard.json"
trap 'rm -rf "$GUARD_DIR"' EXIT

python3 -m py_compile \
  scripts/memory_federation_attestation.py \
  scripts/memory_federation_full_attestation.py \
  scripts/memory_federation_execution_guard.py \
  scripts/verify_memory_federation_implementation.py \
  scripts/verify_memory_federation_status.py
python3 scripts/memory_federation_execution_guard.py self-test
python3 scripts/memory_federation_execution_guard.py capture \
  --state "$GUARD_STATE" \
  --expected-sha "$CANDIDATE_SHA" \
  --expected-tree "$CANDIDATE_TREE"
python3 scripts/verify_memory_federation_status.py verify
python3 scripts/verify_memory_federation_implementation.py \
  --expected-sha "$CANDIDATE_SHA" \
  --expected-tree "$CANDIDATE_TREE"

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

# Cross-host V1 remains a separately qualified protocol/host candidate.  These
# commands prove its source and contracts without silently activating a network
# service.  Doctests enforce that VerifiedFederationFrameV1 cannot be
# constructed or mutated outside the successful verification path.
WIRE_MANIFEST="$ROOT/codex-rs/hepta-memory-federation-wire/Cargo.toml"
cargo fmt --manifest-path "$WIRE_MANIFEST" -- --check
cargo metadata --manifest-path "$WIRE_MANIFEST" --format-version 1 --no-deps > /dev/null
cargo test --manifest-path "$WIRE_MANIFEST" --lib
cargo test --manifest-path "$WIRE_MANIFEST" --doc
cargo clippy --manifest-path "$WIRE_MANIFEST" --all-targets -- -D warnings

cd "$ROOT"
git diff --check
test -z "$(git status --porcelain --untracked-files=no)"
python3 scripts/memory_federation_execution_guard.py verify \
  --state "$GUARD_STATE" \
  --expected-sha "$CANDIDATE_SHA" \
  --expected-tree "$CANDIDATE_TREE"
