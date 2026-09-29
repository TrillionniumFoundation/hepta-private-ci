#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -lt 3 || $# -gt 5 ]]; then
  echo "usage: $0 <source-head|synthetic-merge> <expected-sha> <source-sha> [base-sha] [pr-number]" >&2
  exit 2
fi

CANDIDATE_KIND="$1"
EXPECTED_SHA="$2"
SOURCE_SHA="$3"
BASE_SHA="${4:-}"
PR_NUMBER="${5:-}"
case "$CANDIDATE_KIND" in
  source-head)
    if [[ -n "$BASE_SHA" || -n "$PR_NUMBER" ]]; then
      echo "source-head cannot carry a base SHA or pull-request number" >&2
      exit 2
    fi
    ;;
  synthetic-merge)
    if [[ -z "$BASE_SHA" || ! "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
      echo "synthetic-merge requires a base SHA and positive pull-request number" >&2
      exit 2
    fi
    ;;
  *)
    echo "unsupported candidate kind: $CANDIDATE_KIND" >&2
    exit 2
    ;;
esac

MSRV="${PLATFORM_TYPES_MSRV:-1.96.0}"
MIRI_TOOLCHAIN="${PLATFORM_TYPES_MIRI:-nightly-2026-09-20}"
FUZZ_TOOLCHAIN="${PLATFORM_TYPES_FUZZ_TOOLCHAIN:-$MIRI_TOOLCHAIN}"
OUT="${PLATFORM_TYPES_EVIDENCE_ROOT:-$ROOT/.hepta-evidence/platform-types-deep/$CANDIDATE_KIND}"
MANIFEST="$ROOT/codex-rs/Cargo.toml"
PACKAGE="codex-hepta-types"
WIRE_PACKAGE="codex-hepta-wire"
API_BASE_SHA="${PLATFORM_TYPES_API_BASE_SHA:-${BASE_SHA:-}}"
if [[ -z "$API_BASE_SHA" || "$API_BASE_SHA" =~ ^0+$ ]]; then
  API_BASE_SHA="$(git rev-parse HEAD^)"
fi

rm -rf "$OUT"
mkdir -p "$OUT"

IDENTITY_ARGS=(
  --candidate-kind "$CANDIDATE_KIND"
  --expected-sha "$EXPECTED_SHA"
  --source-sha "$SOURCE_SHA"
)
if [[ "$CANDIDATE_KIND" == synthetic-merge ]]; then
  IDENTITY_ARGS+=(--base-sha "$BASE_SHA" --pr-number "$PR_NUMBER")
fi

declare -A OUTCOMES=()

run_step() {
  local name="$1"
  shift
  set +e
  (
    set -euo pipefail
    "$@"
  ) 2>&1 | tee "$OUT/$name.log"
  local code="${PIPESTATUS[0]}"
  set -u
  if [[ "$code" -eq 0 ]]; then
    OUTCOMES["$name"]="success"
  else
    OUTCOMES["$name"]="failure"
  fi
  return 0
}

truth_check() {
  test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"
  python3 scripts/platform_types_candidate_bundle.py self-test
  python3 scripts/platform_types_rama_lock_guard.py
  python3 -m unittest \
    scripts/test_platform_types_rama_lock_guard.py \
    scripts/test_platform_types_rustdoc_api.py
  python3 scripts/platform_types_public_api.py
  python3 scripts/platform_types_implementation_map.py \
    --output "$OUT/generated-implementation-map.json"
  python3 scripts/platform_types_property_checks.py \
    --report "$OUT/property-report.json"
  cargo run --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --bin platform-types-protocol-codegen -- \
    --json "$OUT/protocol-catalog.json" \
    --markdown "$OUT/protocol-catalog.md"
  python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
  node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
  bash scripts/run_platform_types_consumer_qualification.sh
  cargo run --release --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --bin platform-types-registry-bench -- \
    100000 "$OUT/registry-benchmark.json"
  python3 - "$OUT/registry-benchmark.json" <<'PY'
import json
import pathlib
import sys

value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert value["schema"] == "hepta.platform-types.registry-lookup-benchmark.v1"
assert value["schemaVersion"] == 1
assert value["iterationsPerLookup"] == 100000
assert value["acceptanceThreshold"] is None
assert [row["entryCount"] for row in value["cases"]] == [8, 256]
for row in value["cases"]:
    for field in (
        "constructionElapsedNs",
        "constructionNsPerEntry",
        "identityElapsedNs",
        "identityNsPerLookup",
        "digestElapsedNs",
        "digestNsPerLookup",
        "registryIdentityElapsedNs",
        "registryIdentityNsPerLookup",
    ):
        assert isinstance(row[field], int) and row[field] >= 0
PY
  git diff --check
  test -z "$(git status --porcelain --untracked-files=no)"
}

provenance_check() {
  python3 scripts/platform_types_provenance.py \
    "${IDENTITY_ARGS[@]}" --output "$OUT/provenance.json"
}

api_check() {
  PLATFORM_TYPES_MIRI="$MIRI_TOOLCHAIN" \
    bash scripts/run_platform_types_rustdoc_semver.sh \
    "$API_BASE_SHA" "$EXPECTED_SHA" "$OUT/rustdoc-api"
}

msrv_check() {
  rustup toolchain install "$MSRV" --profile minimal
  rustc "+$MSRV" --version --verbose
  cargo "+$MSRV" check --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --package "$WIRE_PACKAGE" --all-targets
  cargo "+$MSRV" test --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --package "$WIRE_PACKAGE" --all-targets
}

native_check() {
  rustc --version --verbose
  cargo test --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --package "$WIRE_PACKAGE" --all-targets
  cargo clippy --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --package "$WIRE_PACKAGE" --all-targets -- -D warnings
}

miri_check() {
  rustup toolchain install "$MIRI_TOOLCHAIN" --profile minimal \
    --component miri --component rust-src
  rustc "+$MIRI_TOOLCHAIN" --version --verbose
  cargo "+$MIRI_TOOLCHAIN" miri setup
  cargo "+$MIRI_TOOLCHAIN" miri test --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --lib
}

fuzz_check() {
  PLATFORM_TYPES_FUZZ_TOOLCHAIN="$FUZZ_TOOLCHAIN" \
    bash scripts/run_platform_types_coverage_fuzz.sh "$OUT/coverage-fuzz"
}

bundle_check() {
  python3 scripts/platform_types_candidate_bundle.py render \
    "${IDENTITY_ARGS[@]}" \
    --output-dir "$OUT/document-bundle"
}

run_step truth truth_check
run_step provenance provenance_check
run_step api api_check
run_step msrv msrv_check
run_step native native_check
run_step miri miri_check
run_step fuzz fuzz_check
run_step bundle bundle_check

OUTCOME_ARGS=()
for name in truth provenance api msrv native miri fuzz bundle; do
  OUTCOME_ARGS+=(--outcome "$name=${OUTCOMES[$name]}")
done

EVIDENCE_ARGS=(
  --evidence "truth-log=$OUT/truth.log"
  --evidence "provenance-log=$OUT/provenance.log"
  --evidence "api-log=$OUT/api.log"
  --evidence "msrv-log=$OUT/msrv.log"
  --evidence "native-log=$OUT/native.log"
  --evidence "miri-log=$OUT/miri.log"
  --evidence "fuzz-log=$OUT/fuzz.log"
  --evidence "bundle-log=$OUT/bundle.log"
  --evidence "generated-map=$OUT/generated-implementation-map.json"
  --evidence "property-report=$OUT/property-report.json"
  --evidence "registry-benchmark=$OUT/registry-benchmark.json"
  --evidence "protocol-catalog=$OUT/protocol-catalog.json"
  --evidence "protocol-catalog-markdown=$OUT/protocol-catalog.md"
  --evidence "provenance=$OUT/provenance.json"
  --evidence "rustdoc-base=$OUT/rustdoc-api/base-api.json"
  --evidence "rustdoc-current=$OUT/rustdoc-api/current-api.json"
  --evidence "rustdoc-diff=$OUT/rustdoc-api/diff.json"
  --evidence "fuzz-summary=$OUT/coverage-fuzz/summary.json"
  --evidence "bundle-manifest=$OUT/document-bundle/manifest.json"
)

set +e
python3 scripts/platform_types_candidate_bundle.py diagnostics \
  "${IDENTITY_ARGS[@]}" \
  "${OUTCOME_ARGS[@]}" \
  "${EVIDENCE_ARGS[@]}" \
  --output "$OUT/diagnostics.json" \
  2>&1 | tee "$OUT/diagnostics.log"
DIAGNOSTICS_CODE="${PIPESTATUS[0]}"
set -u

ALL_PASSED=true
for name in truth provenance api msrv native miri fuzz bundle; do
  if [[ "${OUTCOMES[$name]}" != success ]]; then
    ALL_PASSED=false
  fi
done
if [[ "$DIAGNOSTICS_CODE" -ne 0 ]]; then
  ALL_PASSED=false
fi

RECEIPT_CODE=1
if [[ "$ALL_PASSED" == true ]]; then
  set +e
  python3 scripts/platform_types_candidate_bundle.py receipt \
    "${IDENTITY_ARGS[@]}" \
    "${OUTCOME_ARGS[@]}" \
    "${EVIDENCE_ARGS[@]}" \
    --msrv-toolchain "$MSRV" \
    --miri-toolchain "$MIRI_TOOLCHAIN" \
    --output "$OUT/qualification-receipt.json" \
    2>&1 | tee "$OUT/receipt.log"
  RECEIPT_CODE="${PIPESTATUS[0]}"
  set -u
else
  printf '%s\n' "receipt not emitted: one or more required checks failed" \
    | tee "$OUT/receipt.log"
fi

{
  printf 'candidate_kind=%s\n' "$CANDIDATE_KIND"
  printf 'expected_sha=%s\n' "$EXPECTED_SHA"
  for name in truth provenance api msrv native miri fuzz bundle; do
    printf '%s=%s\n' "$name" "${OUTCOMES[$name]}"
  done
  printf 'diagnostics=%s\n' "$([[ "$DIAGNOSTICS_CODE" -eq 0 ]] && echo success || echo failure)"
  printf 'receipt=%s\n' "$([[ "$RECEIPT_CODE" -eq 0 ]] && echo success || echo not_emitted_or_failed)"
} > "$OUT/status.env"

if [[ "$ALL_PASSED" == true && "$RECEIPT_CODE" -eq 0 ]]; then
  echo "platform.types deep qualification: passed ($CANDIDATE_KIND $EXPECTED_SHA)"
  exit 0
fi

echo "platform.types deep qualification: failed ($CANDIDATE_KIND $EXPECTED_SHA)" >&2
exit 1
