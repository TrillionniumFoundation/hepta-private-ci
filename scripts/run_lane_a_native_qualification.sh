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

# Keep independent failures observable. A failed test must not hide lint or
# the feature-gated production binaries, and no failed command is retried.
status=0
run_check() {
  local result=0
  "$@" || result=$?
  if (( result != 0 && status == 0 )); then
    status=$result
  fi
}

run_check just --justfile "$ROOT/justfile" test --locked "${ARGS[@]}"
run_check cargo clippy --locked --manifest-path "$MANIFEST" "${ARGS[@]}" --all-targets -- -D warnings

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
run_check cargo check --locked --manifest-path "$MANIFEST" \
  --package codex-hepta-supervisor \
  --features production-authority \
  "${BIN_ARGS[@]}"
run_check cargo clippy --locked --manifest-path "$MANIFEST" \
  --package codex-hepta-supervisor \
  --features production-authority \
  "${BIN_ARGS[@]}" \
  -- -D warnings

exit "$status"
