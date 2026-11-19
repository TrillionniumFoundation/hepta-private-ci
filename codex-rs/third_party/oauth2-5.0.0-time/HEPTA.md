# OAuth2 time implementation

The starting source is the official `oauth2 5.0.0` crate from
https://crates.io/api/v1/crates/oauth2/5.0.0/download. Its archive SHA-256 is
`51e219e79014df21a225b1860a479e2dcd7cbd9130f4defd4bd0e191ea31d67d`, matching
the repository's original Cargo.lock. The upstream source commit is
`f3424b4b2190c83c6d031fdc71eed2351d49e0df`.

This is a local source adaptation, not an upstream release or a transparent
Rust API upgrade. It replaces the unmaintained calendar implementation with
`time::OffsetDateTime` and `time::Duration`. Device-code polling, authorization,
backoff, transport and secret comparisons retain their existing control flow.
Token introspection fields retain optional integer Unix seconds, including
floor rounding for negative fractional timestamps. An explicit serde adapter
retains the previous accepted timestamp bounds; timeout arithmetic retains the
previous duration limit and returns errors at the original timestamp bounds.
The `time/large-dates` feature represents the full previous integer range and
`time/wasm-bindgen` preserves the browser clock implementation.

The public `set_time_fn` hook and introspection getter/setter types now use
`time::OffsetDateTime`. They are not source-compatible with external callers
that inject the previous date type. No such custom calls or implementations
were found in the repository or the four direct consumers. Typed leap seconds
are not representable by the new public type; OAuth NumericDate wire fields
are integer seconds. The minimum supported Rust version becomes 1.88, matching
the selected time package; the repository uses Rust 1.96. Some invalid-duration
diagnostics now name the actual time type. These changes are explicit API
limitations, not claims of universal upstream compatibility.

The base64 minimum is narrowed to 0.22.1, the exact version already selected
for oauth2 in the production lock. This prevents Cargo from switching the new
path package to an older 0.21 release while retaining the production codec.
No existing registry dependency version is upgraded or downgraded.

The existing 66 upstream unit tests are preserved. Nine additional tests cover
negative fractional timestamps, optional fields, integer boundaries, malformed
NumericDates, deadline arithmetic across the epoch, explicit/default expiry,
and overflow without panic. Standalone native validation ran all 75 tests
with zero skips. This record does not claim native Windows/macOS or browser
execution. Locked native compilation passed for codex-rmcp-client and
codex-hepta-matrix-sdk, covering their OAuth2/RMCP/Matrix dependency graph.
The complete codex-rmcp-client suite ran 268 tests: 264 passed and four failed,
with seven existing skips. A run using the exact pre-migration Cargo graph
produced the same per-test results. The failures require a writable OAuth lock
directory or real codex executable metadata in this environment. They remain
failures; no test, path, authentication boundary or gate is bypassed. Exact-head
security and native platform gates remain required.

All source modules, examples, README, upgrade notes and both licenses are
retained. Registry lockfiles, VCS packaging metadata, the upstream ignore file
and CI/funding metadata are omitted; the repository Cargo/Bazel graph governs
production dependencies. The excluded path patch has a Bazel alias to the
rules_rs-generated library with the same resolved dependency graph. No advisory
exception, license exception or test filter is introduced.

The exact semantic patch is retained as `HEPTA-TIME-MIGRATION.patch.gz`,
and the original upgrade notes as `UPGRADE.md.gz`. Decompress these files before
inspection or application; provenance records their compressed and original
SHA-256 values. This preserves required diff-context and original documentation
whitespace without adding a whitespace exception.
