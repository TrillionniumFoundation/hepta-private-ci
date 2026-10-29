# Hepta compatibility patch: aws-config-1.13.0

Upstream package: https://static.crates.io/crates/aws-config/aws-config-1.13.0.crate

Registry SHA-256: `939e256cfe0ed68e96d32f194339d88210d5c10685cff0787400158f852c6819`. The archive was verified against
crates.io version metadata before extraction. Original licenses and
`Cargo.toml.orig` are retained; Cargo builds the patched normalized manifest.

## Changes

Advance P-256 to 0.14 and rand to 0.10.3, removing the vulnerable crypto-bigint 0.5 chain. Use ToSec1Point for the same uncompressed JWK coordinates and fallible OS-randomized ECDSA signing; propagate entropy or signing errors through LoginTokenError instead of panicking. No credentials or authentication checks are bypassed.

Remove this override when upstream AWS config adopts the corrected elliptic-curve dependency generation.

## Build and validation scope

The root Cargo `[patch.crates-io]` selects this path package. Bazel's Rust
extension generates the external crate target from its Cargo manifest.
`codex-rs/third_party` is excluded from source-tree Bazel traversal; no standalone
source-tree `BUILD.bazel` is added here. Ordinary workspace tests do not
automatically run vendored package tests. Verification outcomes are recorded in
the dependency-repair evidence, and are not implied by this patch note.

`HEPTA_UPSTREAM_DIFF.patch` records changes against the checksum-verified
archive. The note and diff themselves are excluded from that comparison.
