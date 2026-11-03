#!/usr/bin/env bash
# Fail-closed local source and Rust gate runner for the Hepta codebase.
# Usage:
#   HEPTA_ROOT=/path/hepta-private-ci RUNTIME_ROOT=/path/hepta-runtime \
#   HEPTA_EXPECTED_SHA=<exact-sha> RUNTIME_EXPECTED_SHA=<exact-sha> \
#   bash hepta_local_gate_runner.sh
# Explicitly NON-AUTHORIZING: does not prove independent production FinalUse,
# remote effects, scientific utility or 1..4096-Cell performance.
set -Eeuo pipefail
umask 077

HEPTA_ROOT="${HEPTA_ROOT:-}"
RUNTIME_ROOT="${RUNTIME_ROOT:-}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$(pwd)/hepta-gate-evidence}"
mkdir -p "$EVIDENCE_DIR"
EVIDENCE_DIR="$(cd "$EVIDENCE_DIR" && pwd)"
index="$EVIDENCE_DIR/run.tsv"
printf 'stage\tresult\tsha\n' > "$index"
current_stage=bootstrap
stage_failure() {
  rc=$?
  printf '%s\tFAIL(%s)\t-\n' "$current_stage" "$rc" >> "$index"
  printf 'Gate %s failed, exit %s; evidence: %s\n' "$current_stage" "$rc" "$EVIDENCE_DIR" >&2
  exit "$rc"
}
trap stage_failure ERR

for cmd in git cargo rustc python3 tee; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'bootstrap\tBLOCKED(missing-%s)\t-\n' "$cmd" >> "$index"
    printf 'Missing prerequisite: %s; no success reported.\n' "$cmd" >&2
    exit 2
  fi
done
if [[ -z "$HEPTA_ROOT" || -z "$RUNTIME_ROOT" ]]; then
  printf 'bootstrap\tBLOCKED(missing-checkout-path)\t-\n' >> "$index"
  echo 'HEPTA_ROOT and RUNTIME_ROOT must point to exact local checkouts.' >&2
  exit 2
fi

check_checkout() {
  local label="$1" dir="$2" expected="$3"
  current_stage="${label}-source-custody"
  test -d "$dir/.git" || git -C "$dir" rev-parse --is-inside-work-tree >/dev/null
  local sha
  sha="$(git -C "$dir" rev-parse HEAD)"
  [[ -z "$expected" || "$sha" == "$expected" ]] || {
    printf '%s\tBLOCKED(sha-mismatch)\t%s\n' "$current_stage" "$sha" >> "$index"
    exit 3
  }
  if [[ -n "$(git -C "$dir" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf '%s\tBLOCKED(dirty-checkout)\t%s\n' "$current_stage" "$sha" >> "$index"
    echo "Dirty checkout for $label; source evidence rejected." >&2
    exit 3
  fi
  printf '%s\tPASS\t%s\n' "$current_stage" "$sha" >> "$index"
}
run_gate() {
  local label="$1" dir="$2"
  shift 2
  current_stage="$label"
  printf 'RUN %s: %q' "$label" "$1"
  printf ' %q' "${@:2}"
  printf '\n'
  (cd "$dir" && "$@") 2>&1 | tee "$EVIDENCE_DIR/${label//\//_}.log"
  printf '%s\tPASS\t-\n' "$label" >> "$index"
}
check_checkout hepta "$HEPTA_ROOT" "${HEPTA_EXPECTED_SHA:-}"
check_checkout runtime "$RUNTIME_ROOT" "${RUNTIME_EXPECTED_SHA:-}"

run_gate hepta-source-boundary "$HEPTA_ROOT" python3 qa/meta-network-scale/check_cell_codex_boundary.py
run_gate hepta-boundary-regressions "$HEPTA_ROOT" python3 -m unittest discover -v -s qa/meta-network-scale -p test_cell_codex_boundary.py
run_gate hepta-rust-format "$HEPTA_ROOT/codex-rs" cargo fmt --all -- --check
run_gate hepta-rust-tests "$HEPTA_ROOT/codex-rs" cargo test --locked -p codex-hepta-types -p codex-hepta-operations -p codex-hepta-codex-adapter
run_gate hepta-rust-clippy "$HEPTA_ROOT/codex-rs" cargo clippy --locked -p codex-hepta-types -p codex-hepta-operations -p codex-hepta-codex-adapter --all-targets -- -D warnings
run_gate runtime-source-contract "$RUNTIME_ROOT" python3 -m unittest discover -v -s scripts -p test_runtime_ci_contract.py
run_gate runtime-rust-format "$RUNTIME_ROOT" cargo fmt --all -- --check
run_gate runtime-rust-check "$RUNTIME_ROOT" cargo check --locked --all-targets
run_gate runtime-rust-clippy "$RUNTIME_ROOT" cargo clippy --locked --all-targets -- -D warnings
run_gate runtime-rust-tests "$RUNTIME_ROOT" cargo test --locked --all-targets
run_gate runtime-rust-release "$RUNTIME_ROOT" cargo build --locked --release

printf '%s\tLOCAL_RUST_ONLY_NON_AUTHORIZING\t-\n' "overall" >> "$index"
printf 'Local source/Rust gates passed. NOT a production FinalUse, target-host, NDU, or scale sign-off.\n'
