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
  codex-hepta-authbus-p1-3-qualification
  codex-hepta-bao-adapter
)
ARGS=()
for package in "${PACKAGES[@]}"; do
  ARGS+=(--package "$package")
done

cargo test --locked --manifest-path "$MANIFEST" "${ARGS[@]}"
cargo clippy --locked --manifest-path "$MANIFEST" "${ARGS[@]}" --all-targets -- -D warnings

# Product-composition proof for the narrow signed-text caller. This is kept
# separate from the library package sweep so a socket/readiness failure is
# visible as a product qualification failure rather than a source-only pass.
cargo test --locked --manifest-path "$MANIFEST" --package codex-hepta-agentd \
  --test authbus_text_product
