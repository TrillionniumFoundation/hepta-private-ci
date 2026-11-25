#!/usr/bin/env bash
set -uo pipefail
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_BUILD_JOBS=2
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export RUSTUP_TOOLCHAIN=1.96.0
export RUST_MIN_STACK=8388608
cd "/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-notes-drain-lock-fix"
git diff --quiet HEAD -- || exit 90
test "$(git rev-parse HEAD)" = "1246ec31781559d54516441c18dba14bc79543f9" || exit 92
git rev-parse HEAD > ../finite-notes-positive-v1.source
sha256sum codex-rs/hepta-memory/src/lib.rs codex-rs/hepta-agentd/src/lib.rs > ../finite-notes-positive-v1.bytes-before
test "$(git rev-parse HEAD:codex-rs/hepta-memory)" = "$(git rev-parse 95cd485f5f9cf362d19ca56c428e3492a632a545:codex-rs/hepta-memory)" || exit 94
touch codex-rs/hepta-agentd/src/lib.rs
sha256sum codex-rs/hepta-memory/src/lib.rs codex-rs/hepta-agentd/src/lib.rs > ../finite-notes-positive-v1.bytes-after
cmp ../finite-notes-positive-v1.bytes-before ../finite-notes-positive-v1.bytes-after || exit 93
just test --locked --offline --cargo-profile dev-small -p codex-hepta-agentd --lib --test-threads 1 --retries 0 -E 'test(notes_objective) | test(finite_notes) | test(notes_organ) | test(actual_reconciler) | test(notes_recovered_writer)' > ../finite-notes-positive-v1.log 2>&1
status=$?
git diff --quiet HEAD -- || status=91
printf '%s\n' "$status" > ../finite-notes-positive-v1.exit
exit "$status"

