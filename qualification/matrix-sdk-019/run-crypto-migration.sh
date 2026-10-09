#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# The old vulnerable release is used only as a no-network synthetic fixture
# producer in its own locked workspace/target; it never enters the product graph.
CARGO_TARGET_DIR="${RUNNER_TEMP:-$fixture}/hepta-legacy-crypto-target" cargo +1.96.0 run --locked \
  --manifest-path "$root/qualification/matrix-sdk-019/legacy-generator/Cargo.toml" \
  -- "$fixture/legacy"
if [[ -n ${HEPTA_SDK_ARTIFACTS:-} ]]; then
  mkdir -p "$HEPTA_SDK_ARTIFACTS"
  tar -czf "$HEPTA_SDK_ARTIFACTS/synthetic-sdk018-crypto-input.tar.gz" -C "$fixture/legacy" .
fi
cd "$root/codex-rs"
HEPTA_LEGACY_CRYPTO_FIXTURE="$fixture/legacy" just test --locked --retries 0 \
  -p codex-hepta-matrix-sdk --features crypto-migration-qualification --test crypto_store_upgrade
