#!/usr/bin/env bash
set -uo pipefail
export PATH=/home/qian-qi/.cargo/bin:$PATH
export CARGO_HOME=/home/qian-qi/.cargo
export CARGO_TARGET_DIR=/data/organ-hepta-integration-target-20261023
export CARGO_BUILD_JOBS=2
export RUSTUP_TOOLCHAIN=1.96.0
export RUST_MIN_STACK=8388608
cd /home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-4/work/goal-effect-entry-guard
git diff --quiet HEAD -- || exit 90
git rev-parse HEAD > ../effect-entry-negative-source-v1.txt
python3 - <<'FRESHNESS'
import hashlib, json, subprocess
from pathlib import Path
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip() == 'bd88e9f34b6e4a612bddd13856b8aaf38dc49f53'
p=Path('codex-rs/hepta-memory/src/lib.rs')
before=hashlib.sha256(p.read_bytes()).hexdigest()
p.touch()
after=hashlib.sha256(p.read_bytes()).hexdigest()
assert before == after
Path('../effect-entry-negative-freshness-v1.json').write_text(json.dumps({'path':str(p.resolve()),'sha256_before':before,'sha256_after':after,'reason':'force intended worktree crate compilation without changing frozen bytes'})+'\n')
FRESHNESS
status=$?
if [ "$status" != 0 ]; then exit "$status"; fi
just test --locked --offline --cargo-profile dev-small -p codex-hepta-memory --lib --test-threads 2 --retries 0 -E 'test(managed_effect_entry_never_dispatches_before_bound_entered_cut_ack)' > ../effect-entry-negative-v1.log 2>&1
status=$?
git diff --quiet HEAD -- || status=91
printf '%s\n' "$status" > ../effect-entry-negative-v1.exit
exit "$status"
