# Hepta compatibility patch: matrix-sdk-sqlite-0.19.1

Upstream package: https://static.crates.io/crates/matrix-sdk-sqlite/matrix-sdk-sqlite-0.19.1.crate

Registry SHA-256: `8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`. The archive was verified against
crates.io version metadata before extraction. Original licenses and
`Cargo.toml.orig` are retained; Cargo builds the patched normalized manifest.

## Changes

Change only the normalized rusqlite constraint from 0.40.2 to 0.39. SQLx 0.9 and rusqlite 0.39 share libsqlite3-sys 0.37, preserving the SQLite WAL-reset fix and the single native links crate. SQL, migration files and store implementation are unchanged.

Remove this override when upstream Matrix SDK and SQLx use the same libsqlite3-sys generation.

## Build and validation scope

The root Cargo `[patch.crates-io]` selects this path package. Bazel's Rust
extension generates the external crate target from its Cargo manifest.
`codex-rs/third_party` is excluded from source-tree Bazel traversal; no standalone
source-tree `BUILD.bazel` is added here. Ordinary workspace tests do not
automatically run vendored package tests. Verification outcomes are recorded in
the dependency-repair evidence, and are not implied by this patch note.

`HEPTA_UPSTREAM_DIFF.patch` records changes against the checksum-verified
archive. The note and diff themselves are excluded from that comparison.
