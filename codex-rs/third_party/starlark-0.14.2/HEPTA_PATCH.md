# Hepta compatibility patch: starlark-0.14.2

Upstream package: https://static.crates.io/crates/starlark/starlark-0.14.2.crate

Registry SHA-256: `9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`. The archive was verified against
crates.io version metadata before extraction. Original licenses and
`Cargo.toml.orig` are retained; Cargo builds the patched normalized manifest.

## Changes

Advance the normalized exact BLAKE3 pin from 1.8.2 to 1.8.7 so the refreshed cryptography graph can share the corrected release. Starlark runtime source is unchanged.

Remove this override when upstream Starlark permits the selected BLAKE3 release.

## Build and validation scope

The root Cargo `[patch.crates-io]` selects this path package. Bazel's Rust
extension generates the external crate target from its Cargo manifest.
`codex-rs/third_party` is excluded from source-tree Bazel traversal; no standalone
source-tree `BUILD.bazel` is added here. Ordinary workspace tests do not
automatically run vendored package tests. Verification outcomes are recorded in
the dependency-repair evidence, and are not implied by this patch note.

`HEPTA_UPSTREAM_DIFF.patch` records changes against the checksum-verified
archive. The note and diff themselves are excluded from that comparison.
