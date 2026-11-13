#!/usr/bin/env bash
set -uo pipefail
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export CARGO_BUILD_JOBS=2
export RUSTUP_TOOLCHAIN=1.96.0
cd /home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-notes-drain-lock-fix
git diff --quiet HEAD -- || exit 90
git rev-parse HEAD > ../finite-notes-fix-source-v3.txt
just fix --locked --offline --profile dev-small -p codex-hepta-agentd > ../finite-notes-fix-v3.log 2>&1
status=$?
git diff --stat > ../finite-notes-fix-diff-v3.txt
printf '%s\n' "$status" > ../finite-notes-fix-v3.exit
exit "$status"
