#!/usr/bin/env bash
# Read-only qualification of a committed source or deterministic merge candidate.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
: "${NEURON_SOURCE_SHA:?pin the source commit}"
: "${NEURON_BASE_SHA:?pin the integration base}"
: "${NEURON_CANDIDATE:?source-head or synthetic-merge}"
: "${NEURON_EVIDENCE_DIR:?retain the evidence outside the worktree}"
mkdir -p "$NEURON_EVIDENCE_DIR"
test "$(git rev-parse HEAD)" = "$NEURON_SOURCE_SHA"
git diff --exit-code
git diff --cached --exit-code
case "$NEURON_CANDIDATE" in
  source-head) ;;
  synthetic-merge)
    export GIT_AUTHOR_DATE=2000-01-01T00:00:00Z
    export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
    git -c user.name=neuron-qualification -c user.email=qualification@invalid.local \
      merge --no-ff --no-edit "$NEURON_BASE_SHA"
    ;;
  *) echo "unknown candidate" >&2; exit 2 ;;
esac
export NEURON_ACTUAL_SHA=$(git rev-parse HEAD)
export NEURON_ACTUAL_TREE=$(git rev-parse HEAD^{tree})
python3 - <<'PY'
import json, os, pathlib
keys = ('NEURON_SOURCE_SHA', 'NEURON_BASE_SHA', 'NEURON_CANDIDATE', 'NEURON_ACTUAL_SHA', 'NEURON_ACTUAL_TREE')
out = {k.lower(): os.environ[k] for k in keys}
out.update(schema='hepta.neuron.qualification.identity.v2', activation=False, independent_acceptance=False)
pathlib.Path(os.environ['NEURON_EVIDENCE_DIR'], 'identity.json').write_text(json.dumps(out, indent=2)+'\n')
PY
failed=0
run_step() {
  local name=$1
  shift
  set +e
  "$@" > >(tee "$NEURON_EVIDENCE_DIR/$name.log") 2>&1
  local code=$?
  set -e
  printf '%s\n' "$code" > "$NEURON_EVIDENCE_DIR/$name.exit"
  if [ "$code" -ne 0 ]; then failed=1; fi
}
run_step measurement-parser python3 -m unittest discover -s scripts/neuron -p 'test_*.py'
run_step teacher-connectivity python3 -m unittest discover \
  -s codex-rs/hepta-neuron/qualification -p 'test_teacher_connectivity.py' -v
run_step decision-cell-metrics python3 -m unittest discover \
  -s codex-rs/hepta-neuron/qualification -p 'test_decision_cell_metrics.py' -v
run_step decision-cell-snapshot python3 -m unittest discover \
  -s codex-rs/hepta-neuron/qualification -p 'test_snapshot_identity.py' -v
run_step decision-cell-loader python3 -m unittest discover \
  -s codex-rs/hepta-neuron/qualification -p 'test_laya_loader_view.py' -v
cd codex-rs
rustc -Vv | tee "$NEURON_EVIDENCE_DIR/toolchain.txt"
pkgs=(-p codex-hepta-neuron -p codex-hepta-infer-worker-host -p codex-hepta-agentd -p codex-hepta-intelligence)
run_step compile cargo check --locked "${pkgs[@]}" --all-targets

# Agentd is a shared package. Compile and lint all targets, but keep this
# qualification lane scoped to Neuron-owned Agentd tests. Repository-wide CI
# continues to execute unrelated Agentd owners.
run_step neuron-owned-tests just test --locked --retries 0 \
  -p codex-hepta-neuron -p codex-hepta-infer-worker-host -p codex-hepta-intelligence
run_step agentd-neuron-tests just test --locked --retries 0 \
  -p codex-hepta-agentd -E 'test(/neuron_runtime_v2/)'

run_step clippy cargo clippy --locked "${pkgs[@]}" --all-targets --no-deps -- -D warnings
run_step format cargo fmt "${pkgs[@]}" -- --check
export HEPTA_NEURON_DIAGNOSTIC_SOURCE_SHA="$NEURON_ACTUAL_SHA"
run_step diagnostic just test --locked -p codex-hepta-neuron --run-ignored only \
  -E 'test(runtime_v2_diagnostic_measurements)' --success-output immediate
cd "$root"
run_step diagnostic-summary python3 scripts/neuron/summarize_measurements.py \
  "$NEURON_EVIDENCE_DIR/diagnostic.log" --source-sha "$NEURON_ACTUAL_SHA" \
  --output "$NEURON_EVIDENCE_DIR/diagnostic-summary.json"
run_step source-unchanged git diff --exit-code
printf 'executed_lane_passed=%s\nactivation=false\nindependent_acceptance=false\n' \
  "$([ "$failed" -eq 0 ] && echo true || echo false)" > "$NEURON_EVIDENCE_DIR/result.txt"
exit "$failed"
