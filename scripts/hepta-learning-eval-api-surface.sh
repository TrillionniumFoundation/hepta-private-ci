#!/usr/bin/env bash
set -Eeuo pipefail

report_failure() {
  local status="$?"
  local command="${BASH_COMMAND}"
  trap - ERR
  command="${command//'%'/'%25'}"
  command="${command//$'\r'/'%0D'}"
  command="${command//$'\n'/'%0A'}"
  printf '::error title=learning.eval API surface::exit=%s command=%s\n' \
    "${status}" "${command}" >&2
  exit "${status}"
}
trap report_failure ERR

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/codex-rs"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

artifact() {
  python3 - "$1" "$2" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
found = set()
for row in rows:
    if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('name') != 'codex_hepta_intelligence_eval':
        continue
    compat = 'trusted-inprocess-eval' in row.get('features', [])
    if compat != (sys.argv[2] == 'compat'):
        raise SystemExit('wrong feature set in compiler artifact')
    found.update(str(pathlib.Path(name).resolve()) for name in row['filenames'] if name.endswith('.rlib'))
if len(found) != 1:
    raise SystemExit(f'expected one exact evaluator rlib, found {len(found)}')
result = pathlib.Path(next(iter(found)))
if not result.is_file():
    raise SystemExit('compiler-reported artifact is missing')
print(result)
PY
}

dependency_artifact() {
  python3 - "$1" "$2" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
found = set()
for row in rows:
    if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('name') != sys.argv[2]:
        continue
    found.update(str(pathlib.Path(name).resolve()) for name in row['filenames'] if name.endswith('.rlib'))
if len(found) != 1:
    raise SystemExit(f'expected one exact {sys.argv[2]} rlib, found {len(found)}')
result = pathlib.Path(next(iter(found)))
if not result.is_file():
    raise SystemExit(f'compiler-reported {sys.argv[2]} artifact is missing')
print(result)
PY
}

dependency_dir() {
  local rlib="$1"
  local directory
  directory="$(dirname "${rlib}")"
  if [[ "$(basename "${directory}")" == "deps" ]]; then
    printf '%s\n' "${directory}"
  elif [[ -d "${directory}/deps" ]]; then
    printf '%s\n' "${directory}/deps"
  else
    echo "compiler-reported dependency directory is missing for ${rlib}" >&2
    return 1
  fi
}

cargo build --locked -p codex-hepta-intelligence-eval --message-format=json >"${tmp}/default-build.jsonl"
rlib="$(artifact "${tmp}/default-build.jsonl" default)"
ledger_rlib="$(dependency_artifact "${tmp}/default-build.jsonl" codex_hepta_learning_ledger)"
deps="$(dependency_dir "${rlib}")"

cat >"${tmp}/positive.rs" <<'RS'
use codex_hepta_intelligence_eval::admit_signed_eligibility_v2;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
#[allow(dead_code)]
fn recorded<S: FinalHoldoutCasStoreV1>(owner: FencedFinalHoldoutOwnerV1<S>) {
    let _ = RecordedProductEvaluationRunnerV1::new(owner);
}
#[allow(dead_code)]
fn anchored<A: codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1>() {
    fn durable<J: DurableProductEvaluationAttemptJournalV1>() {}
    durable::<codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1<A>>();
}
#[allow(dead_code)]
fn verified_recovery<J: DurableProductEvaluationAttemptJournalV1>() {
    let _ = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_qualification::<J>;
    let _ = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_outcome_qualification::<J>;
}
fn main() { let _ = admit_signed_eligibility_v2; }
RS
rustc --edition=2024 --crate-name learning_eval_positive_surface \
  "${tmp}/positive.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
  -L "dependency=${deps}" -o "${tmp}/positive"

for symbol in decide_with_signed_evidence_v2 decide_with_signed_longitudinal_evidence_v3 ProductEvaluationRunnerV1
do
  printf 'use codex_hepta_intelligence_eval::%s;\nfn main() {}\n' "${symbol}" >"${tmp}/negative.rs"
  if rustc --edition=2024 --crate-name learning_eval_negative_surface --error-format=json \
      "${tmp}/negative.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
      -L "dependency=${deps}" -o "${tmp}/negative" \
      >"${tmp}/negative.stdout" 2>"${tmp}/negative.stderr"
  then
    echo "forbidden default API is importable: ${symbol}" >&2
    exit 1
  fi
  python3 - "${tmp}/negative.stderr" "${symbol}" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
expected = any(row.get('level') == 'error'
    and (row.get('code') or {}).get('code') in {'E0432', 'E0603'}
    and sys.argv[2] in row.get('message', '') for row in rows)
if not expected:
    raise SystemExit(f'negative API fixture failed for an unrelated reason: {sys.argv[2]}')
PY
done

for method in qualify_and_persist qualify_outcomes_and_persist
do
  cat >"${tmp}/unarchived.rs" <<RS
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
fn bypass<J: DurableProductEvaluationAttemptJournalV1>() {
    let _ = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::${method}::<J>;
}
fn main() {}
RS
  if rustc --edition=2024 --crate-name learning_eval_unarchived_qualification --error-format=json \
      "${tmp}/unarchived.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
      -L "dependency=${deps}" -o "${tmp}/unarchived" \
      >"${tmp}/unarchived.stdout" 2>"${tmp}/unarchived.stderr"
  then
    echo "unarchived recorded qualification is publicly callable: ${method}" >&2
    exit 1
  fi
  python3 - "${tmp}/unarchived.stderr" "${method}" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(row.get('level') == 'error' and (row.get('code') or {}).get('code') == 'E0624'
           and sys.argv[2] in row.get('message', '') for row in rows):
    raise SystemExit(f'unarchived qualification fixture failed for an unrelated reason: {sys.argv[2]}')
PY
done

cat >"${tmp}/unverified_resume.rs" <<'RS'
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
fn bypass<J: DurableProductEvaluationAttemptJournalV1>() {
    let _ = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_publication::<J>;
}
fn main() {}
RS
if rustc --edition=2024 --crate-name learning_eval_unverified_resume --error-format=json \
    "${tmp}/unverified_resume.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
    -L "dependency=${deps}" -o "${tmp}/unverified_resume" \
    >"${tmp}/unverified_resume.stdout" 2>"${tmp}/unverified_resume.stderr"
then
  echo "unverified decision publication is publicly callable" >&2
  exit 1
fi
python3 - "${tmp}/unverified_resume.stderr" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(row.get('level') == 'error' and (row.get('code') or {}).get('code') == 'E0624'
           and 'resume_decided_publication' in row.get('message', '') for row in rows):
    raise SystemExit('unverified recovery fixture failed for an unrelated reason')
PY

cat >"${tmp}/volatile.rs" <<'RS'
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::InMemoryProductEvaluationAttemptJournalV1;
fn durable<J: DurableProductEvaluationAttemptJournalV1>() {}
fn main() { durable::<InMemoryProductEvaluationAttemptJournalV1>(); }
RS
if rustc --edition=2024 --crate-name learning_eval_volatile_surface --error-format=json \
    "${tmp}/volatile.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
    -L "dependency=${deps}" -o "${tmp}/volatile" \
    >"${tmp}/volatile.stdout" 2>"${tmp}/volatile.stderr"
then
  echo "in-memory journal incorrectly satisfies the default durable capability" >&2
  exit 1
fi
python3 - "${tmp}/volatile.stderr" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(row.get('level') == 'error' and (row.get('code') or {}).get('code') == 'E0277'
           and 'InMemoryProductEvaluationAttemptJournalV1' in row.get('message', '') for row in rows):
    raise SystemExit('volatile journal fixture failed for an unrelated reason')
PY

cat >"${tmp}/bare_selected_host_trust.rs" <<'RS'
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

#[allow(dead_code)]
fn bypass<S: FinalHoldoutCasStoreV1, J: DurableProductEvaluationAttemptJournalV1>(
    runner: &RecordedProductEvaluationRunnerV1<S>,
    verifier: &LearningEvidenceVerifierV1,
    journal: &mut J,
) {
    let _ = runner.qualify_and_persist_on_selected_host(
        todo!(),
        todo!(),
        todo!(),
        todo!(),
        todo!(),
        verifier,
        todo!(),
        journal,
        std::path::Path::new(""),
        std::path::Path::new(""),
        todo!(),
    );
}
fn main() {}
RS
if rustc --edition=2024 --crate-name learning_eval_bare_selected_host_trust --error-format=json \
    "${tmp}/bare_selected_host_trust.rs" \
    --extern "codex_hepta_intelligence_eval=${rlib}" \
    --extern "codex_hepta_learning_ledger=${ledger_rlib}" \
    -L "dependency=${deps}" -o "${tmp}/bare-selected-host-trust" \
    >"${tmp}/bare-selected-host-trust.stdout" 2>"${tmp}/bare-selected-host-trust.stderr"
then
  echo "selected-host qualification accepts a bare learning-evidence verifier" >&2
  exit 1
fi
python3 - "${tmp}/bare-selected-host-trust.stderr" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(
    row.get('level') == 'error'
    and (row.get('code') or {}).get('code') == 'E0308'
    and 'ActivatedLearningTrustV1' in (row.get('rendered') or row.get('message', ''))
    and 'LearningEvidenceVerifierV1' in (row.get('rendered') or row.get('message', ''))
    for row in rows
):
    raise SystemExit('selected-host activated-trust fixture failed for an unrelated reason')
PY

cat >"${tmp}/scalar_selected_host_time.rs" <<'RS'
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;

#[allow(dead_code)]
fn bypass<S: FinalHoldoutCasStoreV1, J: DurableProductEvaluationAttemptJournalV1>(
    runner: &RecordedProductEvaluationRunnerV1<S>,
    trust: &ActivatedLearningTrustV1,
    journal: &mut J,
) {
    let _ = runner.qualify_and_persist_on_selected_host(
        todo!(),
        todo!(),
        todo!(),
        todo!(),
        todo!(),
        trust,
        0_u64,
        journal,
        std::path::Path::new(""),
        std::path::Path::new(""),
        todo!(),
    );
}
fn main() {}
RS
if rustc --edition=2024 --crate-name learning_eval_scalar_selected_host_time --error-format=json \
    "${tmp}/scalar_selected_host_time.rs" \
    --extern "codex_hepta_intelligence_eval=${rlib}" \
    --extern "codex_hepta_learning_ledger=${ledger_rlib}" \
    -L "dependency=${deps}" -o "${tmp}/scalar-selected-host-time" \
    >"${tmp}/scalar-selected-host-time.stdout" 2>"${tmp}/scalar-selected-host-time.stderr"
then
  echo "selected-host qualification accepts a caller-provided scalar time" >&2
  exit 1
fi
python3 - "${tmp}/scalar-selected-host-time.stderr" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(
    row.get('level') == 'error'
    and (row.get('code') or {}).get('code') == 'E0308'
    and 'SelectedHostClockV1' in (row.get('rendered') or row.get('message', ''))
    and 'u64' in (row.get('rendered') or row.get('message', ''))
    for row in rows
):
    raise SystemExit('selected-host clock fixture failed for an unrelated reason')
PY

for symbol in recover_persisted_qualification recover_persisted_outcome_qualification \
  recover_selected_host_qualification recover_selected_host_outcome_qualification
do
  cat >"${tmp}/callback.rs" <<RS
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
fn bypass<J: DurableProductEvaluationAttemptJournalV1>() {
    let _ = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::${symbol}::<J, ()>;
}
fn main() {}
RS
  if rustc --edition=2024 --crate-name learning_eval_callback_surface --error-format=json \
      "${tmp}/callback.rs" --extern "codex_hepta_intelligence_eval=${rlib}" \
      -L "dependency=${deps}" -o "${tmp}/callback" \
      >"${tmp}/callback.stdout" 2>"${tmp}/callback.stderr"
  then
    echo "recovery still accepts a caller-supplied decoder type: ${symbol}" >&2
    exit 1
  fi
  python3 - "${tmp}/callback.stderr" "${symbol}" <<'PY'
import json
import pathlib
import sys
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not any(row.get('level') == 'error' and (row.get('code') or {}).get('code') == 'E0107'
           and sys.argv[2] in (row.get('rendered') or '') for row in rows):
    raise SystemExit(f'callback-removal fixture failed for an unrelated reason: {sys.argv[2]}')
PY
done

cargo build --locked -p codex-hepta-intelligence-eval --features trusted-inprocess-eval \
  --message-format=json >"${tmp}/compat-build.jsonl"
compat="$(artifact "${tmp}/compat-build.jsonl" compat)"
compat_deps="$(dependency_dir "${compat}")"
printf 'use codex_hepta_intelligence_eval::ProductEvaluationRunnerV1;\nfn main() {}\n' >"${tmp}/compat.rs"
rustc --edition=2024 --crate-name learning_eval_compat_surface "${tmp}/compat.rs" \
  --extern "codex_hepta_intelligence_eval=${compat}" -L "dependency=${compat_deps}" \
  -o "${tmp}/compat"
printf '%s\n' '{"schema":"hepta.learning-eval.api-surface.v1","publicAdmission":true,"publicRecordedRunner":true,"verifiedRecoveryPublic":true,"callerDecisionDecoderAccepted":false,"bareVerifierSelectedHostAccepted":false,"callerScalarSelectedHostTimeAccepted":false,"unarchivedRecordedQualificationPublic":false,"unarchivedOutcomeQualificationPublic":false,"unverifiedPublicationRecoveryPublic":false,"lowLevelV2Public":false,"lowLevelV3Public":false,"volatileJournalDefaultAccepted":false,"rawRunnerDefaultPublic":false,"rawRunnerExplicitCompatibilityPublic":true}'
