#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_BRANCH:?TARGET_BRANCH is required}"
: "${EXPECTED_SHA:?EXPECTED_SHA is required}"
: "${PATCH_FILE:?PATCH_FILE is required}"

readonly EXPECTED_PATCH_SHA256="9f4cb4c2c777a2cc2c512cd4951b001c32beba540533467f9dbddf6537b707b4"
readonly ROOT="$(pwd)"
readonly CARGO_ROOT="${ROOT}/codex-rs"

observed_patch_sha="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
test "$observed_patch_sha" = "$EXPECTED_PATCH_SHA256"
test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"
test -z "$(git status --porcelain --untracked-files=normal)"
git fetch --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}"
test "$(git rev-parse refs/remotes/origin/${TARGET_BRANCH})" = "$EXPECTED_SHA"

git apply -p4 --check "$PATCH_FILE"
git apply -p4 "$PATCH_FILE"
(
  cd "$CARGO_ROOT"
  cargo fmt \
    --package codex-hepta-cognitive-store \
    --package codex-hepta-memory \
    --package codex-hepta-agentd
)
git diff --check

python3 - <<'PY'
import subprocess
expected = {
    "codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs",
    "codex-rs/hepta-agentd/tests/cognitive_store_host_read_pages.rs",
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
    "codex-rs/hepta-memory/examples/cognitive_store_recovery_perf.rs",
    "codex-rs/hepta-memory/src/cognitive_schema_tests.rs",
    "codex-rs/hepta-memory/src/cognitive_store_recovery.rs",
    "codex-rs/hepta-memory/src/lib.rs",
    "codex-rs/hepta-memory/tests/cognitive_recovery_publication_fault.rs",
    "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json",
}
observed = set(
    subprocess.check_output(["git", "diff", "--name-only", "HEAD"], text=True)
    .splitlines()
)
if observed != expected:
    raise SystemExit(
        "unexpected remediation change set: "
        f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}"
    )
PY

export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-${RUNNER_TEMP}/cargo-target}"
cd "$CARGO_ROOT"
cargo test --locked -p codex-hepta-agentd \
  --test cognitive_store_product_writer \
  --features qualification-cognitive-write
cargo test --locked -p codex-hepta-agentd \
  --test cognitive_store_host_read_pages
cargo test --locked -p codex-hepta-agentd \
  --test cognitive_recovery_boundary \
  --features qualification-cognitive-write
cargo test --locked -p codex-hepta-memory \
  --test cognitive_recovery_publication_fault
cargo test --locked -p codex-hepta-memory \
  compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected
cargo test --locked -p codex-hepta-memory final_use_tests

HEPTA_COGNITIVE_RECOVERY_RECORDS=256 \
HEPTA_COGNITIVE_RECOVERY_REPETITIONS=1 \
  cargo run --locked --release -p codex-hepta-memory \
    --example cognitive_store_recovery_perf \
    > "${RUNNER_TEMP}/cognitive-recovery-smoke.json"
python3 - <<'PY'
import json
import os
from pathlib import Path
report = json.loads(
    Path(os.environ["RUNNER_TEMP"])
    .joinpath("cognitive-recovery-smoke.json")
    .read_text(encoding="utf-8")
)
assert report["records"] == 256
assert report["repetitions"] == 1
assert len(report["runs"]) == 1
assert report["runs"][0]["exactCutPreserved"] is True
assert report["claimBoundary"]["targetHostQualified"] is False
PY

cargo fmt \
  --package codex-hepta-cognitive-store \
  --package codex-hepta-memory \
  --package codex-hepta-agentd \
  -- --check
cargo clippy --locked \
  -p codex-hepta-cognitive-store \
  -p codex-hepta-memory \
  -p codex-hepta-agentd \
  --all-targets --all-features --no-deps -- -D warnings
cd "$ROOT"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- \
  codex-rs/hepta-agentd/tests/cognitive_recovery_boundary.rs \
  codex-rs/hepta-agentd/tests/cognitive_store_host_read_pages.rs \
  codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs \
  codex-rs/hepta-memory/examples/cognitive_store_recovery_perf.rs \
  codex-rs/hepta-memory/src/cognitive_schema_tests.rs \
  codex-rs/hepta-memory/src/cognitive_store_recovery.rs \
  codex-rs/hepta-memory/src/lib.rs \
  codex-rs/hepta-memory/tests/cognitive_recovery_publication_fault.rs \
  docs/modules/cognitive.store/IMPLEMENTATION_MAP.json
git commit \
  -m "fix(cognitive-store): close exact-candidate recovery blockers" \
  -m "Terminalize raw qualification occurrences before lease release, distinguish the exact recovered witness from the writer-admitted opened cut, and close SQLite pools before descriptor recovery so WAL/SHM teardown cannot race immutable identity binding." \
  -m "Keep redirected or unauthenticated roots indeterminate, use SQLite-safe fixture authority, route schema tests through the state shim, and preserve strict production lint while allowing expect only in test code." \
  -m "Signed-off-by: OpenAI <noreply@openai.com>"
source_sha="$(git rev-parse HEAD)"
source_tree="$(git rev-parse HEAD^{tree})"

python3 scripts/cognitive_store_map_generate.py \
  --source-commit "$source_sha" \
  > "${RUNNER_TEMP}/IMPLEMENTATION_MAP.generated.json"
cp "${RUNNER_TEMP}/IMPLEMENTATION_MAP.generated.json" \
  docs/modules/cognitive.store/IMPLEMENTATION_MAP.json
test "$(git diff --name-only HEAD)" = \
  "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
git diff --check
git add docs/modules/cognitive.store/IMPLEMENTATION_MAP.json
git commit \
  -m "docs(cognitive-store): bind exact recovery-fix source snapshot" \
  -m "Refresh only the exact Git-object implementation map after the reviewed source commit. Execution, target-host, erasure, acceptance, activation and release claims remain false." \
  -m "Signed-off-by: OpenAI <noreply@openai.com>"

mapped_sha="$(git rev-parse HEAD)"
mapped_tree="$(git rev-parse HEAD^{tree})"
python3 scripts/cognitive_store_map_verify.py \
  --expected-sha "$mapped_sha" \
  --expected-tree "$mapped_tree"
python3 scripts/cognitive_store_status.py --check
test -z "$(git status --porcelain --untracked-files=normal)"

git fetch --no-tags origin "+refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}"
test "$(git rev-parse refs/remotes/origin/${TARGET_BRANCH})" = "$EXPECTED_SHA"
test "$(git rev-parse HEAD~2)" = "$EXPECTED_SHA"
git push origin "HEAD:refs/heads/${TARGET_BRANCH}"

{
  echo "Published exact cognitive.store remediation"
  echo "source=${source_sha}"
  echo "source_tree=${source_tree}"
  echo "mapped=${mapped_sha}"
  echo "mapped_tree=${mapped_tree}"
} >> "$GITHUB_STEP_SUMMARY"
