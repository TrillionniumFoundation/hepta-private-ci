#!/usr/bin/env bash
# Same-candidate diagnostics. Failure never leaves a current success report.
set -euo pipefail
[[ $# == 1 ]] || { echo "usage: $0 <output-dir>" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$1"
OUT="$(cd "$1" && pwd)"
cd "$ROOT"

# A baseline is read-only input. Never invalidate it through an output alias.
python3 - "$OUT" "${PLATFORM_TYPES_RESOURCE_BASELINE:-}" <<'PY'
from pathlib import Path
import sys

out = Path(sys.argv[1]).resolve()
if sys.argv[2]:
    baseline = Path(sys.argv[2]).resolve(strict=True)
    if baseline == out or out in baseline.parents:
        raise SystemExit("baseline must be outside the resource output directory")
    for name in ("raw.json", "report.json", "status.json", "verifier-tests.log", "benchmark.log", "gate.log"):
        target = out / name
        if target.exists() and target.samefile(baseline):
            raise SystemExit("baseline aliases a resource output")
PY

# Serialize publication within this output directory without deleting someone
# else's lock. A killed process's lock requires explicit operator reconciliation.
LOCK="$OUT/.resource-qualification-lock"
mkdir "$LOCK" || { echo "resource output is already in use; no files changed" >&2; exit 2; }
TMP_REPORT="$OUT/.resource-report-$$.json"
SOURCE_SHA=""
SOURCE_TREE=""
STAGE=initializing
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 )); then
    rm -f -- "$OUT/report.json" "$TMP_REPORT"
  fi
  if ! python3 - "$OUT/status.json" "$rc" "$STAGE" "$SOURCE_SHA" "$SOURCE_TREE" <<'PY'
import json
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
record = {"schema": "hepta.platform-types.resource-attempt.v1",
          "exitCode": int(sys.argv[2]), "stage": sys.argv[3],
          "sourceHead": sys.argv[4], "sourceTree": sys.argv[5],
          "status": "passed" if sys.argv[2] == "0" else "failed",
          "targetHostQualified": False, "independentAcceptance": False,
          "productActivation": False}
temporary = path.with_name(path.name + ".tmp")
temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
  then
    rc=1
    rm -f -- "$OUT/report.json" "$TMP_REPORT"
  fi
  if ! rmdir "$LOCK"; then
    rc=1
    rm -f -- "$OUT/report.json" "$OUT/status.json"
  fi
  exit "$rc"
}
trap finish EXIT

# Clear only this entrypoint's outputs. In particular remove log symlinks before
# tee can follow them, and remove an earlier pass before any command can fail.
for name in report.json raw.json status.json status.json.tmp verifier-tests.log benchmark.log gate.log; do
  rm -f -- "$OUT/$name"
done
STAGE=identity
SOURCE_SHA="$(git rev-parse HEAD)"
SOURCE_TREE="$(git rev-parse HEAD^{tree})"
test -z "$(git status --porcelain --untracked-files=no)"
ARGS=()
if [[ -n "${PLATFORM_TYPES_RESOURCE_BASELINE:-}" ]]; then
  : "${PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO:?explicit comparison threshold required}"
  ARGS+=(--baseline "$PLATFORM_TYPES_RESOURCE_BASELINE" \
    --maximum-latency-ratio "$PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO")
elif [[ -n "${PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO:-}" ]]; then
  echo "latency threshold requires a baseline" >&2
  exit 2
fi
STAGE=verifier-tests
python3 -m unittest discover -s scripts -p test_platform_types_resource_gate.py -v \
  2>&1 | tee "$OUT/verifier-tests.log"
STAGE=benchmark
cargo run --release --locked --manifest-path "$ROOT/codex-rs/Cargo.toml" \
  --package codex-hepta-types --bin platform-types-semantic-bench -- "$OUT/raw.json" \
  2>&1 | tee "$OUT/benchmark.log"
STAGE=gate
python3 scripts/platform_types_resource_gate.py --raw "$OUT/raw.json" \
  --report "$TMP_REPORT" --source-sha "$SOURCE_SHA" --tree-sha "$SOURCE_TREE" \
  "${ARGS[@]}" 2>&1 | tee "$OUT/gate.log"
STAGE=final-identity
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
test -z "$(git status --porcelain --untracked-files=no)"
# Publish only after the final fence, on the same filesystem.
mv -- "$TMP_REPORT" "$OUT/report.json"
STAGE=complete
