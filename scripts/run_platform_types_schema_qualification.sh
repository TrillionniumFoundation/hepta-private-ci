#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output-dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$1"
MANIFEST="$ROOT/codex-rs/Cargo.toml"
PACKAGE="codex-hepta-types"

rm -rf "$OUT"
mkdir -p "$OUT"

SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_TREE="$(git -C "$ROOT" rev-parse HEAD^{tree})"
INITIAL_STATUS="$(git -C "$ROOT" status --porcelain --untracked-files=no)"
test -z "$INITIAL_STATUS"

CARGO_TARGET_DIR="$OUT/target" \
  cargo run --locked --manifest-path "$MANIFEST" \
    --package "$PACKAGE" --bin platform-types-protocol-codegen -- \
    --json "$OUT/protocol-catalog.json" \
    --markdown "$OUT/protocol-catalog.md" \
    2>&1 | tee "$OUT/codegen.log"

python3 "$ROOT/scripts/verify_platform_types_schema_catalog.py" \
  --catalog "$OUT/protocol-catalog.json" \
  --report "$OUT/schema-catalog-report.json" \
  2>&1 | tee "$OUT/schema-catalog.log"

python3 "$ROOT/scripts/verify_platform_types_semantic_bounds.py" \
  --catalog "$OUT/protocol-catalog.json" \
  --report "$OUT/semantic-bounds-report.json" \
  2>&1 | tee "$OUT/semantic-bounds.log"

(cd "$ROOT" && python3 -m unittest discover -s scripts \
  -p test_platform_types_semantic_bounds.py -v) \
  2>&1 | tee "$OUT/semantic-bounds-tests.log"

FINAL_SHA="$(git -C "$ROOT" rev-parse HEAD)"
FINAL_TREE="$(git -C "$ROOT" rev-parse HEAD^{tree})"
FINAL_STATUS="$(git -C "$ROOT" status --porcelain --untracked-files=no)"
test "$SOURCE_SHA" = "$FINAL_SHA"
test "$SOURCE_TREE" = "$FINAL_TREE"
test -z "$FINAL_STATUS"

python3 - "$OUT" "$SOURCE_SHA" "$SOURCE_TREE" <<'PY'
import hashlib
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
artifacts = {}
for name in (
    "protocol-catalog.json",
    "protocol-catalog.md",
    "schema-catalog-report.json",
    "codegen.log",
    "schema-catalog.log",
    "semantic-bounds-report.json",
    "semantic-bounds.log",
    "semantic-bounds-tests.log",
):
    path = out / name
    raw = path.read_bytes()
    artifacts[name] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
receipt = {
    "schema": "hepta.platform-types.schema-qualification.v1",
    "schemaVersion": 1,
    "sourceSha": sys.argv[2],
    "sourceTree": sys.argv[3],
    "artifacts": artifacts,
    "status": "passed",
    "claimBoundary": (
        "same-candidate Rust catalog/schema structural and Prompt capacity parity; "
        "not activation, external acceptance, promotion, or release"
    ),
}
(out / "receipt.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

echo "platform.types schema qualification: passed ($SOURCE_SHA)"
