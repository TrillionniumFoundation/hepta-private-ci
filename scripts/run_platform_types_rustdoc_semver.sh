#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <base-sha> <candidate-sha> <output-dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_SHA="$1"
CANDIDATE_SHA="$2"
OUT="$3"
TOOLCHAIN="${PLATFORM_TYPES_RUSTDOC_TOOLCHAIN:-${PLATFORM_TYPES_MIRI:-nightly-2026-09-20}}"
MANIFEST="$ROOT/codex-rs/Cargo.toml"
PACKAGE="codex-hepta-types"
TEMP_ROOT="$(mktemp -d)"
BASE_WORKTREE="$TEMP_ROOT/base"

cd "$ROOT"
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
git cat-file -e "$BASE_SHA^{commit}"
rm -rf "$OUT"
mkdir -p "$OUT"

cleanup() {
  git worktree remove --force "$BASE_WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

rustup toolchain install "$TOOLCHAIN" --profile minimal

git worktree add --detach "$BASE_WORKTREE" "$BASE_SHA"

CARGO_TARGET_DIR="$OUT/base-target" \
  cargo "+$TOOLCHAIN" rustdoc --locked \
  --manifest-path "$BASE_WORKTREE/codex-rs/Cargo.toml" \
  --package "$PACKAGE" --lib -- \
  -Z unstable-options --output-format json

CARGO_TARGET_DIR="$OUT/current-target" \
  cargo "+$TOOLCHAIN" rustdoc --locked \
  --manifest-path "$MANIFEST" \
  --package "$PACKAGE" --lib -- \
  -Z unstable-options --output-format json

BASE_JSON="$(find "$OUT/base-target/doc" -maxdepth 1 -name 'codex_hepta_types.json' -print -quit)"
CURRENT_JSON="$(find "$OUT/current-target/doc" -maxdepth 1 -name 'codex_hepta_types.json' -print -quit)"
test -n "$BASE_JSON"
test -n "$CURRENT_JSON"

python3 scripts/platform_types_rustdoc_api.py snapshot \
  --rustdoc-json "$BASE_JSON" --output "$OUT/base-api.json"
python3 scripts/platform_types_rustdoc_api.py snapshot \
  --rustdoc-json "$CURRENT_JSON" --output "$OUT/current-api.json"
python3 scripts/platform_types_rustdoc_api.py diff \
  --old "$OUT/base-api.json" --new "$OUT/current-api.json" \
  --output "$OUT/diff.json"
