#!/usr/bin/env bash
# Same candidate diagnostics; no source mutation or target-host acceptance.
set -euo pipefail
[[ $# == 1 ]] || { echo "usage: $0 <output-dir>" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$1"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
cd "$ROOT"
SOURCE_SHA="$(git rev-parse HEAD)"
SOURCE_TREE="$(git rev-parse HEAD^{tree})"
test -z "$(git status --porcelain --untracked-files=no)"
python3 -m unittest discover -s scripts -p test_platform_types_resource_gate.py -v \
  2>&1 | tee "$OUT/verifier-tests.log"
cargo run --release --locked --manifest-path "$ROOT/codex-rs/Cargo.toml" \
  --package codex-hepta-types --bin platform-types-semantic-bench -- "$OUT/raw.json" \
  2>&1 | tee "$OUT/benchmark.log"
ARGS=()
if [[ -n "${PLATFORM_TYPES_RESOURCE_BASELINE:-}" ]]; then
  : "${PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO:?explicit comparison threshold required}"
  ARGS+=(--baseline "$PLATFORM_TYPES_RESOURCE_BASELINE" \
    --maximum-latency-ratio "$PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO")
elif [[ -n "${PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO:-}" ]]; then
  echo "latency threshold requires a baseline" >&2
  exit 2
fi
python3 scripts/platform_types_resource_gate.py --raw "$OUT/raw.json" \
  --report "$OUT/report.json" --source-sha "$SOURCE_SHA" --tree-sha "$SOURCE_TREE" \
  "${ARGS[@]}" 2>&1 | tee "$OUT/gate.log"
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
test "$(git rev-parse HEAD^{tree})" = "$SOURCE_TREE"
test -z "$(git status --porcelain --untracked-files=no)"
