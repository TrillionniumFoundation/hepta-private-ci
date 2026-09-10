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
cargo clippy --locked --manifest-path "$MANIFEST" "${ARGS[@]}" --all-targets -- -D warnings
