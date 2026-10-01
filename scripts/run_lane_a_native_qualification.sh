#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/codex-rs/Cargo.toml"
PACKAGES=(
  codex-hepta-types
  codex-hepta-wire
  codex-hepta-contracts
  codex-hepta-operations
  codex-hepta-evidence
  codex-hepta-authbus
  codex-hepta-bao-adapter
)
ARGS=()
for package in "${PACKAGES[@]}"; do
  ARGS+=(--package "$package")
done

cargo test --locked --manifest-path "$MANIFEST" "${ARGS[@]}"
# Lint the Lane A packages themselves. Workspace dependencies are qualified by
# their owning lanes; linting them here makes an unrelated package warning a
# false-negative for the platform.wire qualification boundary.
cargo clippy --locked --manifest-path "$MANIFEST" "${ARGS[@]}" --all-targets --no-deps -- -D warnings

# The final-use issuer/approver/revocation-distributor tools are deliberately
# feature-gated. Compile and lint the explicit production-authority surface so
# a green Lane A candidate proves these binaries, not merely the default library.
AUTHORITY_BINS=(
  hepta-final-use-signer
  hepta-final-use-approver
  hepta-final-use-revocation-signer
)
BIN_ARGS=()
for binary in "${AUTHORITY_BINS[@]}"; do
  BIN_ARGS+=(--bin "$binary")
done
cargo check --locked --manifest-path "$MANIFEST" \
  --package codex-hepta-supervisor \
  --features production-authority \
  "${BIN_ARGS[@]}"
cargo clippy --locked --manifest-path "$MANIFEST" \
  --package codex-hepta-supervisor \
  --features production-authority \
  "${BIN_ARGS[@]}" \
  --no-deps \
  -- -D warnings
