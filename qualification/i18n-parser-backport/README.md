# Maintained i18n configuration parser

This candidate is based on `6e552daa20614b128fe50cbcef253fc5c8e6e428`
(Draft #4703). It removes the unmaintained `basic-toml` dependency used by
`age` through `i18n-embed-fl` and `i18n-config`.

## Source and compatibility

The vendored package is the official `i18n-config` 0.4.8 archive, SHA256
`3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`.
Eight original files are included. The original license, README, changelog,
Fluent configuration and gettext configuration are byte-identical. The two
manifests select the already-resolved `toml` 0.9.11+spec-1.1.0 parser with
`parse`, `serde` and `std`. The only functional Rust changes are the two parsing
calls and their error payload type. Repository formatting splits imports.
`official-package.json` records every original file, included or omitted.

This backports the approach in [the upstream parser replacement](https://github.com/kellpossible/cargo-i18n/commit/2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4)
without importing its workspace, edition, dependency or enum-renaming changes.
It follows the narrow implementation reviewed in [Draft #2961](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2961).
The source allowlist does not admit the upstream Git repository, so this
candidate uses the existing path-patch convention and leaves policy unchanged.

Configuration fields, defaults, traversal, parent selection and the existing
`CannotPaseI18nToml` spelling remain unchanged. `CannotDeserializeToml` still
carries the original path and a parser error, but its error payload changes
from `basic_toml::Error` to `toml::de::Error`; diagnostic wording can differ.
The current `i18n-embed-fl` consumer displays that error rather than depending
on the old parser type. `age` remains at 0.11.2. Its encryption implementation,
key material, ciphertext format and storage paths are not changed.

Six public-entry regressions are retained from the existing secrets-consumer
test blob `5cb66a03385ed25a77c49ba02f10e9acbb8a2cd0` in [Draft #3067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3067).
Only the comment identifying the current age version changes. They exercise
the actual parser through the existing `codex-secrets` test target: the shipped
Fluent profile, Cargo metadata, gettext defaults and overrides, parent
selection, and invalid profiles/manifests with their original error paths.
Historical test passes are not counted as this candidate's result.

## Current evidence

| Check | Result |
| --- | --- |
| Cargo resolver | PASS offline; removes basic-toml and replaces i18n-config with the path patch |
| Other packages | 1,518 records remain byte-equivalent as parsed lock entries; no other versions, checksums or dependency edges change |
| Repository formatter | `just fmt` PASS before native execution |
| Same-database cargo-deny | 8 to 7 advisory errors; licenses, bans and sources have zero errors; policy unchanged |
| First native attempt | Original secrets recipe stops while compiling openssl-sys because pkg-config is missing; tests did not run |
| Native after isolated tool installation | PASS: original `just test -p codex-secrets` recipe, 15 tests passed, zero skipped, zero retries |
| Bazel lock and external crate build | Initial Draft awaits the exact hosted generator and original lock check |
| Complete required CI | Pending; DRAFT/HOLD |

The advisory database is `6c5fedf8ff03c485ed674d8f941e0180f3f72d70`.
RUSTSEC-2026-0374 is absent from the actual new audit. The remaining errors are
RUSTSEC-2024-0449, RUSTSEC-2026-0318, RUSTSEC-2026-0319,
RUSTSEC-2026-0370, RUSTSEC-2026-0371, RUSTSEC-2026-0372 and
RUSTSEC-2026-0387. No ignore, license allowance, source allowance, test skip,
retry increase or required-check change is introduced.

The 15 executed tests include all six parser regressions and the existing nine
secrets tests, including local encryption round trips and ciphertext-cache
invalidation. The native receipt binds the input hashes before and after
execution, the resulting test binary, the complete log and the 15-case JUnit
report. This is the Linux consumer suite; complete required CI remains open.
The full cargo-deny output is retained losslessly as `cargo-deny-output.json.gz`
with hashes and a verified decompression check in its adjacent manifest.

## Reproduction

Use pinned Rust/Cargo 1.95.0, cargo-deny 0.19.0, the recorded advisory database,
and real cargo-nextest 0.9.151. The local test environment uses a separate
temporary target directory, one compilation job, no incremental cache and
debug information disabled to bound disk usage. These settings do not alter
the test selection or assertions.

```bash
just fmt
CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_TEST_DEBUG=0 \
  CARGO_PROFILE_DEV_DEBUG=0 just test -p codex-secrets \
  --locked --offline --no-tests=fail --retries 0
cargo deny --manifest-path codex-rs/Cargo.toml --all-features --locked \
  check --disable-fetch --show-stats
just bazel-lock-update
./scripts/check-module-bazel-lock.sh
./.github/scripts/run_bazel_with_buildbuddy.py build \
  @crates//:zip @crates//:i18n-config
```

The temporary read-only workflow checks out the exact PR commit, runs the
existing lock generator and original check, retains the generated bytes and
input hashes, inspects actual external targets, and builds only the two
patched dependency libraries. The generated lock must be adopted and checked
again before this dependency change is considered ready. Those library builds
do not replace the secrets tests or complete required CI.
