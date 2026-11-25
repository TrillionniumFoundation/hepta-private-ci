# Syntect codec and YAML maintenance

This is the complete published Syntect 5.3.0 package, with its original assets,
license, tests, and additional test inputs recovered from its recorded upstream
commit and four exact submodule commits. `HEPTA_SOURCE.json` records the original
archive checksum, file hashes, functional patch, later lint fixes, and formatting.
Each additional fixture has an independently verified Git blob ID and SHA-256 in
the referenced `UPSTREAM_FIXTURE_SOURCE.json` receipts.

## Maintained implementations

The normalized manifest aliases `bincode` to maintained `bincode-next =3.2.0`
with `std` and `serde`, and aliases `yaml-rust` to `yaml-rust2 =0.11.1`. All original
Syntect feature names and runtime entry points remain available.

The small private codec adapter explicitly selects the legacy little-endian,
fixed-width encoding used by the original bincode 1 free functions. It uses an
`IoWriter` and explicitly flushes its serialization buffer before returning.
The maintained serde convenience writer can otherwise hide the final buffered
write error during destruction. The existing Syntect compression and outer
writer-finalization behavior is unchanged.

Bincode-next 3.1.1 was rejected because the differential check found that a
truncated vector could be accepted. Version 3.2.0 rejects those boundaries; the
regression tests retain every truncated boundary and failing writer checks.
Existing dump bytes, syntax/theme assets, supported regex backends, and YAML
loading remain supported. No advisory ignore or feature removal is introduced.

## Explicit local API differences

This maintenance patch changes the concrete error type of seven dump functions
from bincode's boxed `ErrorKind` to `Box<dyn Error + Send + Sync + 'static>`.
`ParseSyntaxError::InvalidYaml` and its `From` implementation now use the
maintained `yaml_rust2::scanner::ScanError`. Code that explicitly names the old
dependency types must migrate; this is not claimed to preserve those nominal
types or every dependency-specific error message.

The repository's two consumers were reviewed. `codex-tui` uses the highlighting,
parsing and theme APIs without naming these error types. `two-face` uses inferred
dump results and `unwrap`; its actual syntax and theme consumers are exercised
by the independent differential program.

The original public API snapshot is preserved in `HEPTA-original-public-api.txt`.
The maintained snapshot is reconstructed with exactly the seven dump-return and
three YAML-type entries described above. Its 184 `serde` to `serde_core` path
occurrences are the same trait reexports under the current common dependencies:
an independently built, unmodified original Syntect implementation proves this
exactly, with the same nightly and public API tool. No other public item changes
are accepted. `HEPTA_API_REVIEW.json` and `HEPTA-api-maintenance.patch` record the
review. The original `public_api` test function and its equality assertion remain.

## Validation and reproduction

`HEPTA_VALIDATION.json` records the observed qualification and evidence hashes:
630 codec corpus cases, all six syntax assets, 57,820 actual onig highlighting
lines, 39 themes, 44 failure/reader/writer cases, and 20 YAML cases compare with
the original implementation. The complete original runtime suites plus five
codec regressions pass 124 tests with onig and 124 with fancy-regex. The original
public API assertion also passes. Both canonical workspace locks, strict
cargo-deny, and an actual configured Bazel dependency query pass.

The repository workspace lock controls production dependency resolution. This
excluded vendor also has a canonical standalone lock for its original test
suite; the published historical lock is retained as `HEPTA-original-Cargo.lock`.
Its local nextest profile retains the repository's 30-second slow-test period,
two-period termination threshold and one retry. There are no test exceptions.
The original manifest's four regex dependency optimization settings remain.

From `codex-rs`, with the repository tools installed, the standalone suite is
addressable directly:

```sh
just test --manifest-path third_party/syntect-5.3.0-maintained-codec/Cargo.toml \
  --locked -p syntect --all-features --lib --test error_handling
just test --manifest-path third_party/syntect-5.3.0-maintained-codec/Cargo.toml \
  --locked -p syntect --no-default-features --features default-fancy,metadata \
  --lib --test error_handling
rustup toolchain install --no-self-update --profile minimal nightly-2025-08-02
just test --manifest-path third_party/syntect-5.3.0-maintained-codec/Cargo.toml \
  --locked -p syntect --test public_api
```

The API test uses its pinned nightly to build rustdoc JSON. Prepare that toolchain
and its documentation dependencies before a timed run on a fresh machine. The
recorded qualification used one build job, disabled incremental compilation and
debug information, and preserved the upstream regex optimization settings.

## Verbatim syntax inputs

Five recovered `.rs` files are language inputs, including deliberately invalid
syntax, rather than compiled crate implementation. The repository formatter
recognizes only their exact full paths, byte lengths and SHA-256 values. Missing
files, byte changes and symlinks are errors. Unregistered neighbors and all real
`src` and `tests` Rust files continue through normal formatting. The complete
inventory and upstream Git blob identities are in `HEPTA_VERBATIM_FIXTURES.json`.

`HEPTA-maintenance.patch` records functional changes. `HEPTA-lint-fixes.patch`
records the subsequent scoped `just fix` changes, without weakening original
assertions. Final mechanical `just fmt` changes are recorded separately. Tests
precede those final fix/format steps, following the repository instructions.

The recorded patches `HEPTA-maintenance.patch`, `HEPTA-formatting.patch` are stored as exact evidence carriers.
Run `python3 qa/repository-consolidation/20261115/restore_raw_evidence.py <new-output-dir>`
from the repository root to recover the original paths and bytes before applying them.
The source manifest retains the original patch digests.
