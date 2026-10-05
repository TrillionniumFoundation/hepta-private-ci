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

python3 "$ROOT/scripts/platform_types_fuzz_evidence.py" budgets \
  "$TYPE_RUNS" "$WIRE_RUNS" "$TOOLCHAIN" "$CARGO_FUZZ_VERSION"
rm -rf "$OUT"
mkdir -p \
  "$OUT/types/corpus" "$OUT/types/artifacts" \
  "$OUT/wire/corpus" "$OUT/wire/artifacts"

python3 "$ROOT/scripts/platform_types_fuzz_corpus.py" "$OUT"
python3 "$ROOT/scripts/platform_types_fuzz_evidence.py" preflight "$OUT" "$TYPE_RUNS" "$WIRE_RUNS"

rustup toolchain install "$TOOLCHAIN" --profile minimal
if ! cargo fuzz --version 2>/dev/null | grep -Fx "cargo-fuzz $CARGO_FUZZ_VERSION" >/dev/null; then
  cargo install cargo-fuzz --version "$CARGO_FUZZ_VERSION" --locked --force
fi
if [[ "$(cargo fuzz --version 2>/dev/null)" != "cargo-fuzz $CARGO_FUZZ_VERSION" ]]; then
  echo "platform.types fuzz evidence: installed cargo-fuzz differs from its pinned version" >&2
  exit 1
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

python3 "$ROOT/scripts/platform_types_fuzz_evidence.py" summary \
  "$OUT" "$TOOLCHAIN" "$CARGO_FUZZ_VERSION" "$TYPE_RUNS" "$WIRE_RUNS"
