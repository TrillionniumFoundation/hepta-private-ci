#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/codex-rs"

cargo build --locked -p codex-hepta-intelligence-eval

rlib="$(find target/debug/deps -maxdepth 1 -type f -name 'libcodex_hepta_intelligence_eval-*.rlib' -print | sort | tail -n 1)"
if [[ -z "${rlib}" ]]; then
  echo "learning.eval rlib not found" >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

cat >"${tmp}/positive.rs" <<'RS'
use codex_hepta_intelligence_eval::admit_signed_eligibility_v2;

fn main() {
    let _ = admit_signed_eligibility_v2;
}
RS
rustc \
  --edition=2024 \
  --crate-name learning_eval_positive_surface \
  "${tmp}/positive.rs" \
  --extern "codex_hepta_intelligence_eval=${rlib}" \
  -L dependency=target/debug/deps \
  -o "${tmp}/positive"

for symbol in \
  decide_with_signed_evidence_v2 \
  decide_with_signed_longitudinal_evidence_v3
do
  cat >"${tmp}/negative.rs" <<RS
use codex_hepta_intelligence_eval::${symbol};

fn main() {
    let _ = ${symbol};
}
RS
  if rustc \
    --edition=2024 \
    --crate-name "learning_eval_negative_${symbol}" \
    "${tmp}/negative.rs" \
    --extern "codex_hepta_intelligence_eval=${rlib}" \
    -L dependency=target/debug/deps \
    -o "${tmp}/negative" \
    >"${tmp}/${symbol}.stdout" \
    2>"${tmp}/${symbol}.stderr"
  then
    echo "forbidden learning.eval symbol is externally importable: ${symbol}" >&2
    exit 1
  fi
  if ! grep -Eq "(no .*${symbol}.* in the root|${symbol}.*private|unresolved import)" "${tmp}/${symbol}.stderr"; then
    cat "${tmp}/${symbol}.stderr" >&2
    echo "negative API fixture failed for an unexpected reason: ${symbol}" >&2
    exit 1
  fi
done

printf '%s\n' '{"schema":"hepta.learning-eval.api-surface.v1","publicAdmission":true,"lowLevelV2Public":false,"lowLevelV3Public":false}'
