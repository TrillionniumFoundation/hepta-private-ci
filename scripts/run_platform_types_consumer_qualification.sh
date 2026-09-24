#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/codex-rs/Cargo.toml"

python3 "$ROOT/scripts/verify_platform_types_consumers.py"
python3 "$ROOT/codex-rs/hepta-types/conformance/verify_vectors.py"
node --input-type=module < "$ROOT/codex-rs/hepta-types/conformance/verify_vectors.ts"
python3 "$ROOT/codex-rs/hepta-types/conformance/verify_rejections.py"
node "$ROOT/codex-rs/hepta-types/conformance/verify_rejections.mjs"
python3 "$ROOT/codex-rs/hepta-types/bindings/generate_bindings.py" --check
python3 "$ROOT/codex-rs/hepta-types/bindings/verify_generated.py"
node "$ROOT/codex-rs/hepta-types/bindings/verify_generated.mjs"

cargo check --locked --manifest-path "$MANIFEST" \
  -p codex-hepta-types \
  -p codex-hepta-ndu \
  -p codex-hepta-codex-adapter \
  -p codex-hepta-learning-ledger \
  -p codex-hepta-supervisor \
  --lib

cargo test --locked --manifest-path "$MANIFEST" -p codex-hepta-types --all-targets
# Run the complete consumer package rather than only the newly added filters;
# otherwise a pre-existing owner or numerical regression could be hidden by a
# green platform.types integration slice.
cargo test --locked --manifest-path "$MANIFEST" -p codex-hepta-ndu --lib
cargo test --locked --manifest-path "$MANIFEST" -p codex-hepta-codex-adapter --lib prompt_delivery
cargo test --locked --manifest-path "$MANIFEST" -p codex-hepta-learning-ledger --lib runtime_delivery
cargo test --locked --manifest-path "$MANIFEST" -p codex-hepta-supervisor --lib topology_candidate

# Strictly lint the new NDU library consumer while acknowledging the crate's
# pre-existing deprecated compatibility re-export. Tests are exercised above;
# their legacy expect/deprecation debt remains a separate package-wide signal.
cargo clippy --locked --manifest-path "$MANIFEST" -p codex-hepta-ndu --lib -- \
  -D warnings -A deprecated
