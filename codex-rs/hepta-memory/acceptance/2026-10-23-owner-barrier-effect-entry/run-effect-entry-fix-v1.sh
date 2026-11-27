#!/usr/bin/env bash
set -uo pipefail
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export CARGO_BUILD_JOBS=2
export RUSTUP_TOOLCHAIN=1.96.0
cd /home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-effect-entry-guard-fix
git diff --quiet HEAD -- || exit 90
git rev-parse HEAD > ../effect-entry-fix-source-v1.txt
just fix --locked --offline --profile dev-small -p codex-hepta-memory > ../effect-entry-fix-v1.log 2>&1
status=$?
git diff --stat > ../effect-entry-fix-diff-v1.txt
printf '%s\n' "$status" > ../effect-entry-fix-v1.exit
exit "$status"
