# Hepta compatibility patch: i18n-config-0.4.8

Upstream package: https://static.crates.io/crates/i18n-config/i18n-config-0.4.8.crate

Registry SHA-256: `3e06b90c8a0d252e203c94344b21e35a30f3a3a85dc7db5af8f8df9f3e0c63ef`. The archive was verified against
crates.io version metadata before extraction. Original licenses and
`Cargo.toml.orig` are retained; Cargo builds the patched normalized manifest.

## Changes

Replace unmaintained basic-toml with toml 0.9. Both Cargo.toml and i18n.toml parsing call sites use the new parser; the public CannotDeserializeToml payload is now toml::de::Error. Preserve the original configuration structures and file-path error binding.

Remove this override when upstream i18n-config adopts a maintained TOML parser.

## Build and validation scope

The root Cargo `[patch.crates-io]` selects this path package. Bazel's Rust
extension generates the external crate target from its Cargo manifest.
`codex-rs/third_party` is excluded from source-tree Bazel traversal; no standalone
source-tree `BUILD.bazel` is added here. Ordinary workspace tests do not
automatically run vendored package tests. Verification outcomes are recorded in
the dependency-repair evidence, and are not implied by this patch note.

`HEPTA_UPSTREAM_DIFF.patch` records changes against the checksum-verified
archive. The note and diff themselves are excluded from that comparison.
