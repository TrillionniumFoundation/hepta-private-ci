#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output-dir>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$1"
TOOLCHAIN="${PLATFORM_TYPES_FUZZ_TOOLCHAIN:-nightly-2026-09-20}"
CARGO_FUZZ_VERSION="${PLATFORM_TYPES_CARGO_FUZZ_VERSION:-0.12.0}"
TYPE_RUNS="${PLATFORM_TYPES_TYPE_FUZZ_RUNS:-4096}"
WIRE_RUNS="${PLATFORM_TYPES_WIRE_FUZZ_RUNS:-4096}"

rm -rf "$OUT"
mkdir -p \
  "$OUT/types/fuzz_targets" "$OUT/types/corpus" "$OUT/types/artifacts" \
  "$OUT/wire/fuzz_targets" "$OUT/wire/corpus" "$OUT/wire/artifacts"

rustup toolchain install "$TOOLCHAIN" --profile minimal
if ! cargo fuzz --version 2>/dev/null | grep -F "cargo-fuzz $CARGO_FUZZ_VERSION" >/dev/null; then
  cargo install cargo-fuzz --version "$CARGO_FUZZ_VERSION" --locked --force
fi

cat > "$OUT/types/Cargo.toml" <<EOF
[package]
name = "codex-hepta-types-fuzz-exact-candidate"
version = "0.0.0"
publish = false
edition = "2021"
[package.metadata]
cargo-fuzz = true
[dependencies]
libfuzzer-sys = "0.4"
codex-hepta-types = { path = "$ROOT/codex-rs/hepta-types" }
[[bin]]
name = "canonical_validate"
path = "fuzz_targets/canonical_validate.rs"
test = false
doc = false
bench = false
[workspace]
members = ["."]
EOF
cp "$ROOT/codex-rs/hepta-types/fuzz/fuzz_targets/canonical_validate.rs" \
  "$OUT/types/fuzz_targets/canonical_validate.rs"

cat > "$OUT/wire/Cargo.toml" <<EOF
[package]
name = "codex-hepta-wire-fuzz-exact-candidate"
version = "0.0.0"
publish = false
edition = "2021"
[package.metadata]
cargo-fuzz = true
[dependencies]
libfuzzer-sys = "0.4"
codex-hepta-wire = { path = "$ROOT/codex-rs/hepta-wire" }
[[bin]]
name = "platform_types_json"
path = "fuzz_targets/platform_types_json.rs"
test = false
doc = false
bench = false
[workspace]
members = ["."]
EOF
cp "$ROOT/codex-rs/hepta-wire/fuzz/fuzz_targets/platform_types_json.rs" \
  "$OUT/wire/fuzz_targets/platform_types_json.rs"

(
  cd "$OUT/types"
  cargo "+$TOOLCHAIN" fuzz run canonical_validate corpus \
    -- -runs="$TYPE_RUNS" -max_len=262145 -timeout=5 \
    -artifact_prefix="$OUT/types/artifacts/"
) | tee "$OUT/types.log"

(
  cd "$OUT/wire"
  cargo "+$TOOLCHAIN" fuzz run platform_types_json corpus \
    -- -runs="$WIRE_RUNS" -max_len=65537 -timeout=5 \
    -artifact_prefix="$OUT/wire/artifacts/"
) | tee "$OUT/wire.log"

python3 - "$OUT" "$TOOLCHAIN" "$CARGO_FUZZ_VERSION" "$TYPE_RUNS" "$WIRE_RUNS" <<'PY'
import hashlib
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
records = []
for target in ("types", "wire"):
    log = out / f"{target}.log"
    records.append({
        "target": target,
        "log": log.name,
        "logSha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "artifactFiles": sorted(
            str(path.relative_to(out))
            for path in (out / target / "artifacts").glob("**/*")
            if path.is_file()
        ),
    })
summary = {
    "schema": "hepta.platform-types.coverage-fuzz.v1",
    "schemaVersion": 1,
    "module": "platform.types",
    "toolchain": sys.argv[2],
    "cargoFuzzVersion": sys.argv[3],
    "runs": {"canonicalValidate": int(sys.argv[4]), "platformTypesJson": int(sys.argv[5])},
    "targets": records,
    "status": "passed",
    "claimBoundary": "bounded exact-candidate libFuzzer execution; not exhaustive proof",
}
(out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
PY
