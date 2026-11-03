#!/usr/bin/env bash
# Non-authorizing, non-mutating Hepta local CI evidence runner.
# Usage: bash hepta_local_blocker_runner.sh /path/to/hepta-private-ci /path/to/evidence [offline|online]
set -Eeuo pipefail

PROJECT="${1:-$PWD}"
EVIDENCE="${2:-$PWD/hepta-local-evidence}"
NETWORK_MODE="${3:-offline}"
if [[ "$NETWORK_MODE" != offline && "$NETWORK_MODE" != online ]]; then
  printf 'Usage: %s PROJECT EVIDENCE [offline|online]\n' "$0" >&2
  exit 2
fi
mkdir -p "$EVIDENCE"
EVIDENCE="$(cd "$EVIDENCE" && pwd -P)"
: > "$EVIDENCE/checks.tsv"
export PYTHONDONTWRITEBYTECODE=1
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
if [[ "$NETWORK_MODE" == offline ]]; then export CARGO_NET_OFFLINE=true; fi

write_report() {
  local reason="$1"
  HEPTA_REPORT_REASON="$reason" HEPTA_REPORT_PATH="$EVIDENCE/report.json" HEPTA_TSV="$EVIDENCE/checks.tsv" \
  HEPTA_WORKTREE="${PROJECT}" python3 - <<'PY'
import datetime, json, os, pathlib
p=pathlib.Path(os.environ['HEPTA_TSV'])
checks=[]
for line in p.read_text().splitlines():
    name,status,code,elapsed,log=line.split('\t')
    checks.append({'name':name,'status':status,'exit_code':int(code),'elapsed_seconds':int(elapsed),'log':log})
preflight=os.environ['HEPTA_REPORT_REASON']
report={
  'schema':'hepta.local.execution-evidence.v1',
  'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'project_path':os.environ['HEPTA_WORKTREE'],
  'preflight':preflight,
  'checks':checks,
  'all_executed_checks_passed':bool(checks) and all(x['status']=='PASS' for x in checks),
  'independent_operator_acceptance':False,
  'production_authority_granted':False,
  'physical_target_host_evidence_complete':False,
  'external_blockers_closed':False,
  'deployment_permitted':False,
}
with open(os.environ['HEPTA_REPORT_PATH'],'w',encoding='utf8') as f:
    json.dump(report,f,indent=2,sort_keys=True)
    f.write('\n')
print(json.dumps({'preflight':preflight,'checks':len(checks),'failed':[x['name'] for x in checks if x['status']!='PASS'],'report':os.environ['HEPTA_REPORT_PATH']},ensure_ascii=False))
PY
}

for exe in python3 git; do
  if ! command -v "$exe" >/dev/null 2>&1; then
    echo "BLOCKED_PRECONDITION: $exe missing" >&2
    # Python is required for the local JSON writer; if absent, leave a clear text receipt.
    if [[ "$exe" == python3 ]]; then echo "missing python3" > "$EVIDENCE/report.error"; exit 2; fi
    write_report "BLOCKED_PRECONDITION: $exe missing"
    exit 2
  fi
done
if [[ ! -d "$PROJECT/.git" && ! -f "$PROJECT/.git" ]] || [[ ! -f "$PROJECT/codex-rs/Cargo.toml" ]]; then
  write_report 'BLOCKED_PRECONDITION: exact Hepta Git checkout not mounted'
  exit 2
fi
PROJECT="$(cd "$PROJECT" && pwd -P)"
cd "$PROJECT"
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  write_report 'BLOCKED_PRECONDITION: source checkout is dirty (refusing to certify mixed source)'
  exit 2
fi
if ! command -v rustc >/dev/null || ! command -v cargo >/dev/null; then
  write_report 'BLOCKED_PRECONDITION: local rustc/cargo missing'
  exit 2
fi
printf '%s\n' "$(git rev-parse HEAD)" > "$EVIDENCE/exact-head.txt"
printf '%s\n' "$(git log -1 --format='%P')" > "$EVIDENCE/parents.txt"
rustc --version > "$EVIDENCE/toolchain.txt"
cargo --version >> "$EVIDENCE/toolchain.txt"
printf 'DENY_ALL / HOLD_NO_GO: local CI is NOT production authorization.\n' > "$EVIDENCE/authority.txt"

run_check() {
  local label="$1"; shift
  local name="$(printf '%s' "$label" | tr -cs 'A-Za-z0-9_.-' '_')"
  local log="$EVIDENCE/${name}.log"
  local start end rc=0
  start=$(date +%s)
  printf '%q ' "$@" > "$EVIDENCE/${name}.command"
  printf '\n' >> "$EVIDENCE/${name}.command"
  echo "RUN $label"
  if command -v timeout >/dev/null 2>&1; then
    timeout --signal=TERM --kill-after=10s "${HEPTA_CHECK_TIMEOUT_SECONDS:-1800}s" "$@" > "$log" 2>&1 || rc=$?
  else
    "$@" > "$log" 2>&1 || rc=$?
  fi
  end=$(date +%s)
  local verdict=PASS
  if ((rc!=0)); then verdict=FAIL; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$verdict" "$rc" "$((end-start))" "${name}.log" >> "$EVIDENCE/checks.tsv"
  echo "$verdict $label (exit $rc)"
}

run_check cargo_graph cargo metadata --manifest-path codex-rs/Cargo.toml --locked --no-deps --format-version 1
run_check rustfmt cargo fmt --manifest-path codex-rs/Cargo.toml --package codex-hepta-neuron --package codex-hepta-intelligence --package codex-hepta-infer-worker-host --package codex-hepta-agentd --package codex-hepta-supervisor --package codex-hepta-control-plane -- --check
run_check callers python3 scripts/verify_hepta_callers.py verify
run_check neuron_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-neuron -p codex-hepta-intelligence --lib
run_check worker_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-infer-worker-host --lib
run_check supervisor_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-supervisor --lib
run_check control_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-control-plane --lib
run_check agentd_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd --lib
run_check fleet_tests cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-fleet --lib
run_check strict_clippy cargo clippy --manifest-path codex-rs/Cargo.toml --locked --lib -p codex-hepta-neuron -p codex-hepta-intelligence -p codex-hepta-agentd -p codex-hepta-infer-worker-host -- -D clippy::correctness -D clippy::await_holding_lock -D clippy::await_holding_invalid_type
if [[ -f qa/ndu-grounded-generation/test_cohort_firewall.py ]]; then
  run_check ndu_firewall python3 -m unittest discover -v -s qa/ndu-grounded-generation -p test_cohort_firewall.py
fi
if [[ -f scripts/test_hepta_cell_split_target_matrix.py ]]; then
  run_check p4_matrix_contract python3 -m pytest -q -p no:cacheprovider scripts/test_hepta_cell_split_target_matrix.py
fi
run_check git_diff git diff --check
if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
  printf '%s\n' 'dirty-source-after-test' > "$EVIDENCE/source_mutation.txt"
  printf '%s\tFAIL\t%s\t0\t%s\n' source_integrity 1 source_mutation.txt >> "$EVIDENCE/checks.tsv"
fi
write_report 'EXECUTED_LOCAL_SOURCE_TESTS_ONLY'
if grep -q $'\tFAIL\t' "$EVIDENCE/checks.tsv"; then exit 1; fi
exit 0
