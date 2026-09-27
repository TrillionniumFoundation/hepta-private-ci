#!/usr/bin/env bash
set -euxo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Qualification is read-only. The implementation-map migrator rewrites provenance
# anchors and is intentionally never invoked from a verifier lane: a committed map
# cannot contain the SHA of the commit that contains that same map. Verify the exact
# checked-out candidate instead, including every registered map and mapped source
# object, and require the checkout to stay clean throughout the matrix.
CANDIDATE_SHA="$(git rev-parse HEAD)"
CANDIDATE_TREE="$(git rev-parse HEAD^{tree})"
python3 scripts/hepta-implementation-maps.py verify \
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

# Cross-host V1 is deliberately a separately qualified protocol crate.  It is
# not a workspace member or product caller yet, so these commands prove source
# and protocol behavior without silently activating a network path.
WIRE_MANIFEST="$ROOT/codex-rs/hepta-memory-federation-wire/Cargo.toml"
cargo fmt --manifest-path "$WIRE_MANIFEST" -- --check
cargo metadata --manifest-path "$WIRE_MANIFEST" --format-version 1 --no-deps > /dev/null
cargo test --manifest-path "$WIRE_MANIFEST" --lib
cargo clippy --manifest-path "$WIRE_MANIFEST" --all-targets -- -D warnings

cd "$ROOT"
git diff --check
test -z "$(git status --porcelain --untracked-files=no)"
