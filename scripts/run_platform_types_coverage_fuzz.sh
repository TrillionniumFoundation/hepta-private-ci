#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output-dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).absolute())' "$1")"
TOOLCHAIN="${PLATFORM_TYPES_FUZZ_TOOLCHAIN:-nightly-2026-09-20}"
CARGO_FUZZ_VERSION="${PLATFORM_TYPES_CARGO_FUZZ_VERSION:-0.12.0}"
TYPE_RUNS="${PLATFORM_TYPES_TYPE_FUZZ_RUNS:-4096}"
WIRE_RUNS="${PLATFORM_TYPES_WIRE_FUZZ_RUNS:-4096}"
TYPES_FUZZ_DIR="$ROOT/codex-rs/hepta-types/fuzz"
WIRE_FUZZ_DIR="$ROOT/codex-rs/hepta-wire/fuzz"

rm -rf "$OUT"
mkdir -p \
  "$OUT/types/corpus" "$OUT/types/artifacts" \
  "$OUT/wire/corpus" "$OUT/wire/artifacts"

python3 "$ROOT/scripts/platform_types_fuzz_corpus.py" "$OUT"

rustup toolchain install "$TOOLCHAIN" --profile minimal
if ! cargo fuzz --version 2>/dev/null | grep -F "cargo-fuzz $CARGO_FUZZ_VERSION" >/dev/null; then
  cargo install cargo-fuzz --version "$CARGO_FUZZ_VERSION" --locked --force
fi

# cargo-fuzz discovers the ordinary Cargo project from the current directory and
# treats --fuzz-dir as its dedicated fuzz package. Running from an ad-hoc fuzz
# package itself makes cargo-fuzz search for a missing parent project.
(
  cd "$ROOT/codex-rs"
  cargo "+$TOOLCHAIN" fuzz run \
    --fuzz-dir "$TYPES_FUZZ_DIR" \
    canonical_validate "$OUT/types/corpus" \
    -- -runs="$TYPE_RUNS" -max_len=262145 -timeout=5 \
    -artifact_prefix="$OUT/types/artifacts/"
) 2>&1 | tee "$OUT/types.log"

(
  cd "$ROOT/codex-rs"
  cargo "+$TOOLCHAIN" fuzz run \
    --fuzz-dir "$WIRE_FUZZ_DIR" \
    platform_types_json "$OUT/wire/corpus" \
    -- -runs="$WIRE_RUNS" -max_len=65537 -timeout=5 \
    -artifact_prefix="$OUT/wire/artifacts/"
) 2>&1 | tee "$OUT/wire.log"

python3 - "$OUT" "$TOOLCHAIN" "$CARGO_FUZZ_VERSION" "$TYPE_RUNS" "$WIRE_RUNS" <<'PY'
import hashlib
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
seed_receipt = out / "corpus-seeds.json"
seed_bytes = seed_receipt.read_bytes()
seed_summary = json.loads(seed_bytes)
records = []
for target in ("types", "wire"):
    log = out / f"{target}.log"
    raw = log.read_bytes()
    if not raw:
        raise SystemExit(f"empty libFuzzer log: {log}")
    text = raw.decode("utf-8", errors="replace")
    if "DONE" not in text and "cov:" not in text:
        raise SystemExit(f"libFuzzer completion/coverage marker missing: {log}")
    records.append({
        "target": target,
        "log": log.name,
        "logSha256": hashlib.sha256(raw).hexdigest(),
        "logBytes": len(raw),
        "artifactFiles": sorted(
            str(path.relative_to(out))
            for path in (out / target / "artifacts").glob("**/*")
            if path.is_file()
        ),
    })
summary = {
    "schema": "hepta.platform-types.coverage-fuzz.v2",
    "schemaVersion": 2,
    "module": "platform.types",
    "toolchain": sys.argv[2],
    "cargoFuzzVersion": sys.argv[3],
    "runs": {"canonicalValidate": int(sys.argv[4]), "platformTypesJson": int(sys.argv[5])},
    "corpusSeeds": {
        "receipt": seed_receipt.name,
        "receiptSha256": hashlib.sha256(seed_bytes).hexdigest(),
        "counts": {
            target: sum(row["target"] == target for row in seed_summary["seeds"])
            for target in ("types", "wire")
        },
    },
    "wireDecoders": [
        "PromptDeliveryObservationV2",
        "RuntimeTopologyCandidateV1",
        "RandomStreamManifestV1",
        "ExternalSystemManifestV1",
        "SensorCalibrationManifestV1",
    ],
    "targets": records,
    "status": "passed",
    "claimBoundary": "bounded exact-candidate libFuzzer execution; not exhaustive proof",
}
(out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
PY
