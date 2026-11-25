#!/usr/bin/env bash
set -uo pipefail
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export CARGO_BUILD_JOBS=2
export RUSTUP_TOOLCHAIN=1.96.0
export RUST_MIN_STACK=8388608
cd /home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-notes-retirement-fix
git diff --quiet HEAD -- || exit 90
git rev-parse HEAD > ../notes-retirement-positive-source-v2.txt
just test --locked --offline --cargo-profile dev-small -p codex-hepta-memory --lib --test-threads 2 --retries 0 -E 'test(notes) | test(objective_sender) | test(production_composition)' > ../notes-retirement-positive-v2.log 2>&1
status=$?
git diff --quiet HEAD -- || status=91
printf '%s\n' "$status" > ../notes-retirement-positive-v2.exit
exit "$status"
