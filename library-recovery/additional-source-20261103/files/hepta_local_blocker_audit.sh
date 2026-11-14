#!/usr/bin/env bash
# Hepta MemoryCell: exact-source, read-only verification runner.
# Does not install dependencies, merge branches, promote models, or modify source intentionally.
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: bash hepta_local_blocker_audit.sh <path-to-hepta-private-ci> [--full] [--expect-sha <40-hex>]

Runs fail-closed local CI-style checks in the supplied repository checkout.
Reports are stored outside the repository in $HEPTA_AUDIT_OUTPUT, or a new /tmp directory.
  default  contract/lock/security smoke + targeted MemoryCell research unit tests
  --full   wider Rust/native/verification suites; may be CPU/RAM/time intensive
No script result is independent operational acceptance or proof of held-out gains.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then usage; exit 0; fi
[[ $# -ge 1 ]] || { usage >&2; exit 2; }
REPO=$1; shift
FULL=0; EXPECT_SHA=""
while (( $# )); do
  case "$1" in
    --full) FULL=1; shift;;
    --expect-sha)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      EXPECT_SHA=$2; shift 2
      [[ "$EXPECT_SHA" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "Invalid --expect-sha" >&2; exit 2; };;
    -h|--help) usage; exit 0;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done

command -v git >/dev/null || { echo "git is required" >&2; exit 3; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 3; }
REPO=$(cd "$REPO" && pwd -P) || exit 3
[[ -f "$REPO/README.md" && -f "$REPO/codex-rs/Cargo.toml" && -e "$REPO/.git" ]] || {
  echo "Not a hepta-private-ci source checkout: $REPO" >&2; exit 3;
}
[[ "$(git -C "$REPO" rev-parse --show-toplevel)" == "$REPO" ]] || {
  echo "Not the repository root" >&2; exit 3;
}
SHA=$(git -C "$REPO" rev-parse HEAD)
TREE=$(git -C "$REPO" rev-parse 'HEAD^{tree}')
if [[ -n "$EXPECT_SHA" && "$SHA" != "$EXPECT_SHA" ]]; then
  echo "BASE_DRIFT: expected=$EXPECT_SHA observed=$SHA; no tests run" >&2; exit 4
fi
if [[ -n "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "DIRTY_TREE: source has tracked/untracked edits; no tests run" >&2; exit 4
fi

OUT=${HEPTA_AUDIT_OUTPUT:-"${TMPDIR:-/tmp}/hepta-memory-audit-$(date -u +%Y%m%dT%H%M%SZ)-${SHA:0:12}"}
mkdir -p "$OUT/logs"
OUT=$(cd "$OUT" && pwd -P)
case "$OUT/" in "$REPO/"*) echo "Output must be outside repository" >&2; exit 4;; esac
SUMMARY="$OUT/steps.tsv"
printf 'step\tstatus\texit_code\tlog\n' > "$SUMMARY"
{
  printf 'repo=%s\nsha=%s\ntree=%s\nfull=%s\n' "$REPO" "$SHA" "$TREE" "$FULL"
  git -C "$REPO" show -s --format='head_date=%cI%nhead_subject=%s' HEAD
  for t in git python3 cargo rustc just bazel; do
    if command -v "$t" >/dev/null; then
      printf '%s_version=' "$t"
      "$t" --version 2>&1 | head -1 || true
    else
      printf '%s_version=MISSING\n' "$t"
    fi
  done
} > "$OUT/source.txt"

FAIL=0
run_step() {
  local name=$1; shift
  local log="$OUT/logs/$name.log"
  local code=0
  {
    printf 'SOURCE_SHA=%s\nSOURCE_TREE=%s\n' "$SHA" "$TREE"
    printf 'COMMAND='; printf '%q ' "$@"; printf '\n'
    printf 'WORKING_DIR=%s\n' "$PWD"
    "$@"
  } > "$log" 2>&1 || code=$?
  local state="PASS"
  if (( code != 0 )); then state="FAIL"; FAIL=1; fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$state" "$code" "logs/$name.log" >> "$SUMMARY"
  printf '%-36s %-5s exit=%s\n' "$name" "$state" "$code"
}

require_tool() {
  local name=$1
  if command -v "$name" >/dev/null; then return 0; fi
  printf '%s\tBLOCKED\t127\t%s\n' "prerequisite_$name" "-" >> "$SUMMARY"
  printf 'Missing required tool: %s\n' "$name" >&2
  FAIL=1; return 1
}

cd "$REPO"
run_step git_diff_check git diff --check
run_step docs_development python3 scripts/hepta-docs.py verify --profile development

if [[ -d "$REPO/qa/stem-bakeoff" ]]; then
  run_step memory_retrieval_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_memory_retrieval_probe.py' -v
  run_step procedure_replay_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_procedure_replay.py' -v
  run_step native_procedure_export_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_procedure_native_export.py' -v
  run_step memory_router_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_cell_router_training.py' -v
  run_step memory_evolution_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_cell_evolution.py' -v
  run_step memory_process_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_cell_process_inference.py' -v
  run_step memory_shared_student_unit python3 -m unittest discover -s qa/stem-bakeoff -p 'test_shared_student_training.py' -v
else
  printf 'memory_research_directory\tBLOCKED\t127\t-\n' >> "$SUMMARY"; FAIL=1
fi

cd "$REPO/codex-rs"
if require_tool cargo; then
  run_step cargo_metadata_locked cargo metadata --locked --format-version=1
  run_step rustfmt_check cargo fmt --all -- --check
  if cargo deny --version >/dev/null 2>&1; then
    run_step cargo_deny cargo deny check
  else
    printf 'cargo_deny\tBLOCKED\t127\t-\n' >> "$SUMMARY"; FAIL=1
    echo 'cargo-deny is required for strict security closure' >&2
  fi
fi

if (( FULL )); then
  cd "$REPO"
  run_step docs_readiness python3 scripts/hepta-readiness.py verify
  run_step docs_algorithm python3 scripts/hepta-algorithm-docs.py verify
  run_step docs_hnmf python3 scripts/hepta-hnmf.py verify
  if [[ -d "$REPO/qa/stem-bakeoff" ]]; then
    run_step research_all_units python3 -m unittest discover -s qa/stem-bakeoff -p 'test_*.py' -v
  fi
  cd "$REPO/codex-rs"
  if require_tool just; then
    run_step memory_native_tests just test -p codex-hepta-cognitive-types -p codex-hepta-memory-retrieval -p codex-hepta-neuron -p codex-hepta-learning-artifacts -p codex-hepta-agentd --lib --locked --retries 0
    run_step bazel_lock_check just bazel-lock-check
  fi
fi

cd "$REPO"
run_step final_worktree_clean git diff --exit-code
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'final_untracked_check\tFAIL\t1\t-\n' >> "$SUMMARY"; FAIL=1
  echo 'The source tree is not clean after verification; inspect it manually.' >&2
fi

python3 - "$SUMMARY" "$SHA" "$TREE" "$OUT/report.json" <<'PY'
import csv, json, sys
path, sha, tree, dest = sys.argv[1:]
with open(path, encoding='utf-8') as fp:
    checks = list(csv.DictReader(fp, delimiter='\t'))
flags = [c for c in checks if c['status'] != 'PASS']
report = {
  'schema':'hepta.local-memory-blocker-audit.v1',
  'head_sha':sha,'head_tree':tree,'steps':checks,
  'checks_all_passed': not flags,
  'full_scientific_qualification':False,
  'independent_future_window_evidence':False,
  'production_accepted':False,
  'note':'CI-like local checks alone never certify scientific gain, trusted source or operation authority.'
}
with open(dest, 'w', encoding='utf-8') as fp:
    json.dump(report, fp, ensure_ascii=False, indent=2)
    fp.write('\n')
PY
printf '\nReport: %s/report.json\n' "$OUT"
if (( FAIL )); then
  echo 'HOLD_NO_GO: one or more local checks failed or were blocked' >&2
  exit 1
fi
echo 'LOCAL_CHECKS_PASS_ONLY: independent holdouts, security admission and production authority remain separate.'
