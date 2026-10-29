# Hepta compatibility patch: matrix-sdk-0.19.1

Upstream package: https://static.crates.io/crates/matrix-sdk/matrix-sdk-0.19.1.crate

Registry SHA-256: `2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e`. The archive was verified against
crates.io version metadata before extraction. Original licenses and
`Cargo.toml.orig` are retained; Cargo builds the patched normalized manifest.

## Changes

Replace unmaintained anymap2 with maintained anymap3 1.1 under the existing anymap2 dependency alias. No Matrix runtime source was changed.

Remove this override when the upstream Matrix SDK uses a maintained type-map dependency.

## Build and validation scope

The root Cargo `[patch.crates-io]` selects this path package. Bazel's Rust
extension generates the external crate target from its Cargo manifest.
`codex-rs/third_party` is excluded from source-tree Bazel traversal; no standalone
source-tree `BUILD.bazel` is added here. Ordinary workspace tests do not
automatically run vendored package tests. Verification outcomes are recorded in
the dependency-repair evidence, and are not implied by this patch note.

`HEPTA_UPSTREAM_DIFF.patch` records changes against the checksum-verified
archive. The note and diff themselves are excluded from that comparison.
