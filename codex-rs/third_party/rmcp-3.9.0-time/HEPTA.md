# RMCP time implementation

The starting source is the official `rmcp 3.9.0` crate from
https://crates.io/api/v1/crates/rmcp/3.9.0/download. Its archive SHA-256 is
`d24a7e92f4bcaa36b97fa93c4fa7ca8f3e669eced949345b3462dba333c7f909`, matching
the repository's original Cargo.lock. The upstream source commit is
`5596a8a0bba2a1ec5519cc855cdadf23e4dcecdc` (`crates/rmcp`).

This local source adaptation replaces chrono clocks with
`time::OffsetDateTime`. A small private formatter retains UTC `+00:00`,
fractional precision in groups of three digits, and signed extended years.
Request-state timestamps retain floor rounding of negative Unix milliseconds.
Timeout diagnostics retain the original zero, seconds, fractions and
unrepresentable-duration behavior. Actual timeout scheduling, task state,
request-state HMAC and expiry checks, and production authorization and
transport behavior are unchanged. The unused schemars `chrono04` feature is removed from normal and
development dependencies. `time/wasm-bindgen` retains browser clock support;
the package's existing minimum Rust version remains 1.88.

`Annotations::for_resource` and `Annotations::with_timestamp` now accept
`time::OffsetDateTime`. This is an explicit Rust API change; no repository
callers of these typed constructors were found. The new type cannot construct
typed leap seconds and can represent years beyond the former type's range.
The serialized `lastModified` field remains `Option<String>` and preserves
all supplied strings verbatim, including leap-second, date-only and malformed
values. No JSON schema or serialized field type changes.

The six added tests cover fractional precision, extended years, UTC offset
normalization across date boundaries, raw annotation round-trips, negative
millisecond rounding and timeout diagnostics. A separate oracle includes the
actual formatter implementation and compares it with chrono 0.4.45: all 15
timestamp inputs and 10 duration inputs match.

The standalone original library and selected integration suites started 760
tests. Existing local output records 755 passes, including all six new tests,
but has no terminal result. A later read of that running command was rejected
by automatic approval review because existing HTTP security fixtures use
`mcp.attacker.test`. Those fixtures configure local mock DNS and loopback
listeners, but their HTTP builder also inherits proxy configuration, so local
DNS alone does not prove that every environment confines the requests to
loopback. That command was not retried and the suite is not claimed as passed.
The original tests and security checks remain intact. A subsequent fixture
repair uses the same production resolver, redirect and body-limit construction
with an explicit no-proxy HTTP builder. The fixture DNS lookup has only local
loopback answers and does not fall back to operating-system DNS. Both mock
services bind `127.0.0.1`. Negative discovery cases now require that the
resource metadata was actually fetched, and an additional regression checks
that a configured local proxy receives no requests. Production callers retain
the default builder and their existing proxy behavior. The repaired scoped run completed 23 tests with zero failures and zero retries.
A separate native run executed 1,601 tests across 94 binaries: all 1,601
passed, while four upstream tests requiring live Keycloak remained ignored.
Its original nextest list and JUnit have identical executed case-name sets
and the same run identity. All tests, including the JavaScript and Python
interoperability fixtures, ran as the original unprivileged user in a fresh
Linux network namespace containing only loopback and local routes. Effective
capabilities were zero and NoNewPrivs was enabled. Fixture dependencies were
fetched beforehand; execution used only their offline caches. The original
incomplete run and rejection remain independent evidence. The local non-Send
feature, alternative TLS backends, other platforms and browser execution
remain unqualified.

Fresh locked offline compilation passed for `codex-rmcp-client` and
`codex-hepta-matrix-sdk`. Scoped `just fix -p codex-rmcp-client` completed
successfully; this compiles its tests without executing them. Canonical
repository formatting and Bazel lock generation completed successfully. The
generated Bazel RMCP library depends on time and has no chrono dependency.

All source modules, original tests, schema fixtures, README, changelog and
license are retained. Registry lockfiles and VCS packaging metadata are
omitted; the repository Cargo and Bazel locks govern production dependencies.
Five lossless gzip patch carriers separate the source adaptation, the
repository formatter's mechanical changes, local fixture repair including
its final mechanical formatting, two final documentation spelling fixes, and JavaScript fixture formatting.
The spelling fixes preserve every executable Rust syntax token. The JavaScript
formatting preserves the complete normalized Babel syntax tree; normalization
removes source coordinates and spelling metadata and equates noncomputed
string and identifier property names. Apply
`HEPTA-TIME-MIGRATION.patch.gz`, `HEPTA-REPOSITORY-FORMAT.patch.gz`, then
`HEPTA-LOOPBACK-FIXTURES.patch.gz`, then
`HEPTA-REPOSITORY-SPELLING.patch.gz`, then `HEPTA-JAVASCRIPT-FORMAT.patch.gz`.
Compression preserves unified-diff context bytes without creating
trailing-whitespace errors when this vendor directory is added. Their hashes
and source identities are recorded in `HEPTA-SOURCE-PROVENANCE.json`. No
advisory exception, license exception, authentication relaxation or test
filter is introduced.
