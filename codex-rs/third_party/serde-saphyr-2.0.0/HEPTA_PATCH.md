# Opt-in manifest scalar compatibility

This is the complete published `serde-saphyr 2.0.0` crate. Its official archive is
https://static.crates.io/crates/serde-saphyr/serde-saphyr-2.0.0.crate, SHA-256
`a253edfdea34032da21af84e16fcc94f4c7a6ba237f9f3bc2dbf43cea8535c44`.
The upstream license, original manifest, tests and examples remain intact.

The added `hepta-legacy-scalars` feature is disabled by default. The first-party
`codex-utils-yaml` dependency and this candidate's Bazel library explicitly enable
it. All existing upstream feature definitions and dependency declarations are
unchanged. Without the new feature, the published scalar behavior is preserved;
a separate actual test verifies mixed-case boolean/null, uppercase radix,
underscored integer and large-integer inference in that mode.

The compatibility changes are confined to `src/parse_scalars.rs` and
`src/de/deserializer.rs`:

- Strict boolean and null inference uses the exact spellings accepted by the
  previous manifest parser. Arbitrary mixed case remains a string.
- Integer lexical checks reject uppercase radix prefixes and underscores in the
  compatibility mode. The same helper is used by scalar parsing and integer key
  fingerprints, so key comparison cannot silently merge a string with an integer.
- Untyped inference tries 128-bit integer visitors after the 64-bit range. The
  private Value-like visitor rejects unsupported integer widths, as the previous
  parser did. Literals beyond even the 128-bit range retain the old finite-float
  or string fallback; there is no blanket rejection of every large decimal.
- Leading-zero decimal integers remain strings in untyped positions. Floating
  overflow remains a string unless an explicit numeric tag requires an error.
  Only the legacy parser's exact YAML infinity and NaN spellings are non-finite.

The private first-party projection additionally preserves semantic duplicate-key
checks, application tags, ordinary merge keys and binary-tagged strings. No old
parser is retained in its final dependency graph; no advisory is ignored.

The earlier v3 candidate, its 19-case evidence and its eight-test result remain
preserved. A frozen 37-case differential probe then demonstrated 15 additional
numeric differences in v3. The repaired candidate matched all 37 actual old-parser
outcomes. Those outcomes were frozen into golden tests, the temporary legacy test
dependency was removed, and all nine utility tests passed with a locked graph
containing neither `serde_yaml` nor `unsafe-libyaml`. One additional isolated
no-feature test passed five upstream-default checks. Every invocation used the
repository's `just test` entrypoint and the existing compatibility target cache.

This is bounded compatibility evidence. It does not claim equivalence for every
YAML grammar or target type. Full consumer regressions, coherent Cargo/Bazel locks,
and the unchanged dependency scan remain separate promotion gates.
