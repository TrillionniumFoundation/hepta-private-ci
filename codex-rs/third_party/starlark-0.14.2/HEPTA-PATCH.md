# starlark 0.14.2 compatibility patch

Source: https://static.crates.io/crates/starlark/starlark-0.14.2.crate

Official archive SHA-256: `9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`.

Both published manifests select BLAKE3 1.8.7, retaining every originally
enabled BLAKE3 feature. Matrix SDK 0.19.1's encrypted storage requires at least
this release, while the published Starlark manifest pins 1.8.2 exactly, so Cargo
cannot resolve the unmodified graph. Starlark's only BLAKE3 caller uses the
unchanged inherent Hasher API; no digest trait API or Rust source is changed.
The product's execpolicy tests verify the actual Starlark consumer. This is a
manifest compatibility backport to the official 0.14.2 source, not a renamed
or fabricated upstream release.

The release archive omits its repository license file. LICENSE is copied
from upstream commit 0c8d107ab963362ba47ee3ab9e0173bc39bd101d:
https://raw.githubusercontent.com/facebook/starlark-rust/0c8d107ab963362ba47ee3ab9e0173bc39bd101d/LICENSE

The published standalone Cargo.lock is omitted; product Cargo and Bazel
locks govern the selected graph. This dependency is excluded from product
workspace membership and materialized by Bazel's `@crates` generator.
All first-party features remain included in the original cargo-deny gate.
No advisory ignore or license allowlist is changed.
