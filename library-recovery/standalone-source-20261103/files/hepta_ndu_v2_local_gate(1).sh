#!/usr/bin/env bash
# Read-only / non-authorizing exact-source qualification helper for Hepta PR #3325.
# This does NOT replace the repository's GitHub Actions or independent product review.
set -Eeuo pipefail

EXPECTED_HEAD='28c6448256760c7228ce9af41613f9678e5136b9'
EXPECTED_TREE='e8fda4e0a5f95746c3c682df9c88238da3f388ae'
OUT_DIR="${HEPTA_GATE_OUTPUT:-$(mktemp -d "${TMPDIR:-/tmp}/hepta-ndu-v2-gate.XXXXXXXX")}" 
mkdir -p "$OUT_DIR"
printf 'Output directory: %s\n' "$OUT_DIR"

if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  printf 'BLOCKED: git and python3 are required.\n' >&2
  exit 2
fi
if ! ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  printf 'BLOCKED: no checked-out Hepta Git working tree.\n' >&2
  exit 2
fi
cd "$ROOT"
HEAD="$(git rev-parse HEAD)"
TREE="$(git rev-parse 'HEAD^{tree}')"
if [[ "$HEAD" != "$EXPECTED_HEAD" || "$TREE" != "$EXPECTED_TREE" ]]; then
  printf 'BLOCKED: this helper is pinned to exact source %s (%s).\n' "$EXPECTED_HEAD" "$EXPECTED_TREE" >&2
  printf 'Observed: %s (%s)\n' "$HEAD" "$TREE" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  printf 'BLOCKED: checkout is not clean. Use a disposable clean worktree.\n' >&2
  exit 2
fi

# Content-addressed source claims, not signatures or independent attestations.
while IFS=' ' read -r path sha; do
  [[ -z "$path" ]] && continue
  actual="$(git rev-parse "HEAD:$path")"
  if [[ "$actual" != "$sha" ]]; then
    printf 'BLOCKED: unexpected Git blob %s (expected %s, observed %s)\n' "$path" "$sha" "$actual" >&2
    exit 2
  fi
done <<'BLOBS'
qa/ndu-grounded-generation/cohort_firewall.py 9ce55db769e5975aa67d5d5fbb066c5dce1cee64
qa/ndu-grounded-generation/test_cohort_firewall.py 4f4f2629e7236ab5a33546aa9bb6b1b1b0f24054
qa/ndu-grounded-generation/v2_exclusions.py dfe9123de45dfebf0da97bca827a372b6955812b
qa/ndu-grounded-generation/test_v2_exclusions.py 2f9184cc40c4afe1f48151bfe0c31755e4990192
qa/ndu-grounded-generation/test_v2_cohort_integration.py d11792bb4a0d22f0466e8089fe373ab07c998df5
BLOBS

RESULTS="$OUT_DIR/stages.tsv"
: > "$RESULTS"
failed=0
run_stage() {
  local stage="$1"; shift
  printf 'Running %s\n' "$stage"
  local code=0
  "$@" >"$OUT_DIR/$stage.log" 2>&1 || code=$?
  printf '%s\t%s\t%s\n' "$stage" "$code" "$(if ((code==0)); then echo success; else echo failure; fi)" >> "$RESULTS"
  if ((code!=0)); then failed=1; fi
}
unavailable() {
  printf '%s\t%s\t%s\n' "$1" "-1" "unavailable" >> "$RESULTS"
  failed=1
}

export PYTHONDONTWRITEBYTECODE=1
run_stage source_ast python3 -c 'import ast, pathlib; p=pathlib.Path("qa/ndu-grounded-generation"); [ast.parse(f.read_text(encoding="utf-8"), filename=str(f)) for f in p.glob("*.py")]'
for name in test_cohort_firewall test_capability_gate test_v2_exclusions test_v2_cohort_integration; do
  run_stage "$name" python3 -B -m unittest discover -s qa/ndu-grounded-generation -p "${name}.py" -v
done
run_stage diff_check git diff --check
if command -v ruff >/dev/null 2>&1; then
  run_stage ruff_format ruff format --check qa/ndu-grounded-generation/cohort_firewall.py qa/ndu-grounded-generation/test_cohort_firewall.py qa/ndu-grounded-generation/v2_exclusions.py qa/ndu-grounded-generation/test_v2_exclusions.py qa/ndu-grounded-generation/test_v2_cohort_integration.py
else
  unavailable ruff_format
fi
if command -v just >/dev/null 2>&1; then
  run_stage project_fmt just fmt-check
else
  unavailable project_fmt
fi
if command -v cargo >/dev/null 2>&1; then
  run_stage ndu_cargo bash -c 'cd codex-rs && cargo test --locked -p codex-hepta-ndu --lib'
else
  unavailable ndu_cargo
fi

# The evaluator never changes authority and never converts local tests into a production PASS.
HEPTA_GATE_RESULTS="$RESULTS" HEPTA_GATE_OUTPUT="$OUT_DIR" HEPTA_GATE_FAILED="$failed" \
  HEPTA_GATE_HEAD="$HEAD" HEPTA_GATE_TREE="$TREE" python3 - <<'PY'
import csv, json, os
from pathlib import Path
with open(os.environ['HEPTA_GATE_RESULTS'], encoding='utf-8') as f:
    stages=[dict(stage=row['stage'], exit_code=int(row['exit_code']), status=row['status'])
            for row in csv.DictReader(('stage\texit_code\tstatus\n'+f.read()).splitlines(), delimiter='\t')]
report={
    'schema':'hepta.ndu-v2.local-readonly-gate.v1',
    'source_commit':os.environ['HEPTA_GATE_HEAD'],
    'source_tree':os.environ['HEPTA_GATE_TREE'],
    'local_gate_status':'blocked' if int(os.environ['HEPTA_GATE_FAILED']) else 'local_checks_passed_only',
    'stages':stages,
    'github_exact_head_ci_verified':False,
    'independent_hardware_verdict':None,
    'scientific_ndu_superiority_established':False,
    'final_use_authorized':False,
    'production_admission':False,
}
path=Path(os.environ['HEPTA_GATE_OUTPUT'])/'local-verdict.json'
path.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
print(f'Wrote: {path}')
print(f'Status: {report["local_gate_status"]}; production_admission=false')
PY
if ((failed!=0)); then exit 2; fi
