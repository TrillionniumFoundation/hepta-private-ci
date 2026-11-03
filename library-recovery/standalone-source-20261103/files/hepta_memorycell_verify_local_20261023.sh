#!/usr/bin/env bash
# Local source-preserving research verification runner (tests may create build caches).
# Does not push, merge, deploy, promote, or change selected model artifacts.
# Run from inside an authorized hepta-private-ci checkout.
set -uo pipefail

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo 'BLOCKED: no git checkout; run this script inside the authorized hepta-private-ci worktree' >&2
  exit 2
fi
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo 'BLOCKED: checkout has no committed HEAD; exact-source qualification is impossible' >&2
  exit 2
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
if [[ ! -d qa/stem-bakeoff || ! -d codex-rs ]]; then
  echo 'BLOCKED: this checkout does not contain both qa/stem-bakeoff and codex-rs' >&2
  exit 2
fi

OUT="${1:-/tmp/hepta-memorycell-verify-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
if [[ -e "$OUT" ]]; then
  echo "BLOCKED: output already exists: $OUT" >&2
  exit 2
fi
SOURCE_STATUS="$(git status --porcelain=v1)"
mkdir -p "$OUT/logs"
{
  printf 'repo=%s\n' "$ROOT"
  printf 'head=%s\n' "$(git rev-parse HEAD)"
  printf 'tree=%s\n' "$(git rev-parse HEAD^{tree})"
  printf 'branch=%s\n' "$(git branch --show-current)"
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\n' "$SOURCE_STATUS"
} > "$OUT/source.txt"
if [[ -n "$SOURCE_STATUS" ]]; then
  echo 'WARNING: checkout contains uncommitted changes; generated logs are not exact-commit qualification evidence' >&2
fi
printf 'name\tstatus\texit_code\tcommand\n' > "$OUT/results.tsv"

run() {
  local name="$1"; shift
  local command="$*"
  echo "RUN: $name"
  local code
  bash -o pipefail -c "$command" > "$OUT/logs/${name}.log" 2>&1
  code=$?
  local state='FAIL'
  [[ "$code" == 0 ]] && state='PASS'
  printf '%s\t%s\t%d\t%s\n' "$name" "$state" "$code" "$command" >> "$OUT/results.tsv"
  echo "  $state ($code); log: $OUT/logs/${name}.log"
}

if ! command -v python3 >/dev/null 2>&1; then
  echo 'BLOCKED: python3 unavailable' >&2
  exit 2
fi
# Each test module is a separate blocker row; failures never hide later failures.
for module in \
  test_memory_retrieval_probe.py \
  test_procedure_replay.py \
  test_procedure_replay_verify.py \
  test_procedure_native_export.py \
  test_cell_router_training.py \
  test_cell_evolution.py \
  test_cell_process_inference.py \
  test_real_evolution_probe.py \
  test_shared_student_training.py; do
  name="${module%.py}"
  if [[ ! -f "qa/stem-bakeoff/$module" ]]; then
    printf '%s\t%s\t%d\t%s\n' "$name" MISSING_TEST 127 "qa/stem-bakeoff/$module" >> "$OUT/results.tsv"
    continue
  fi
  run "$name" "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=qa/stem-bakeoff python3 -m unittest discover -s qa/stem-bakeoff -p '$module' -v"
done

if command -v python3 >/dev/null 2>&1; then
  run python_syntax "python3 -c 'import ast, pathlib; [ast.parse(p.read_text(), filename=str(p)) for p in pathlib.Path(\"qa/stem-bakeoff\").glob(\"*.py\")]; print(\"Python AST syntax OK\")'"
fi
if command -v cargo >/dev/null 2>&1; then
  run rustfmt "cd codex-rs && cargo fmt --all -- --check"
else
  printf '%s\t%s\t%d\t%s\n' rustfmt BLOCKED_TOOLCHAIN 127 'cargo fmt --all -- --check' >> "$OUT/results.tsv"
fi
if command -v just >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
  run rust_scoped "cd codex-rs && just test -p codex-hepta-cognitive-types -p codex-hepta-memory-retrieval -p codex-hepta-neuron -p codex-hepta-ndu -p codex-hepta-memory -p codex-hepta-learning-artifacts -p codex-hepta-intelligence --lib --locked --retries 0"
else
  printf '%s\t%s\t%d\t%s\n' rust_scoped BLOCKED_TOOLCHAIN 127 'just test (scoped memory packages)' >> "$OUT/results.tsv"
fi
# Offline full-repo gates are intentionally not substituted for hosted GitHub
# Architecture, blocking-ci, cargo-deny and Linux/macOS/Windows Bazel runs.
if grep -qE $'\t(FAIL|BLOCKED_TOOLCHAIN|MISSING_TEST)\t' "$OUT/results.tsv"; then
  echo "OPEN blockers remain. Inspect $OUT/results.tsv and exact logs."
  exit 1
fi
echo "Local scoped checks passed; this does NOT qualify hosted CI or production. Report: $OUT"
