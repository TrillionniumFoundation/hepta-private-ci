#!/usr/bin/env bash
set -uo pipefail
umask 0077
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_BUILD_JOBS=2
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export RUSTUP_TOOLCHAIN=1.96.0
export RUST_MIN_STACK=8388608
export TMPDIR=$(mktemp -d /data/hfn.XXXXXX)
trap 'rm -rf -- "$TMPDIR"' EXIT
cd "/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-notes-drain-lock-fix"
git diff --quiet HEAD -- || exit 90
test "$(git rev-parse HEAD)" = "3528961a92ef69ff965a12b559952f745d02d109" || exit 92
git rev-parse HEAD > ../finite-notes-positive-v2.source
sha256sum codex-rs/hepta-memory/src/lib.rs codex-rs/hepta-agentd/src/lib.rs > ../finite-notes-positive-v2.bytes-before
touch codex-rs/hepta-memory/src/lib.rs codex-rs/hepta-agentd/src/lib.rs
sha256sum codex-rs/hepta-memory/src/lib.rs codex-rs/hepta-agentd/src/lib.rs > ../finite-notes-positive-v2.bytes-after
cmp ../finite-notes-positive-v2.bytes-before ../finite-notes-positive-v2.bytes-after || exit 93
just test --locked --offline --cargo-profile dev-small -p codex-hepta-agentd --lib --test-threads 1 --retries 0 -E 'test(notes_objective) | test(finite_notes) | test(notes_organ) | test(actual_reconciler) | test(notes_recovered_writer)' > ../finite-notes-positive-v2.log 2>&1
status=$?
git diff --quiet HEAD -- || status=91
printf '%s\n' "$status" > ../finite-notes-positive-v2.exit
exit "$status"
