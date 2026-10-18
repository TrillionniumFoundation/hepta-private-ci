# Hepta compatibility patch

This directory contains the crates.io source package `starlark 0.14.2`,
with its upstream version and license unchanged. The only dependency change
is its exact `blake3` pin from `=1.8.2` to `=1.8.7`; all upstream Rust source
and selected BLAKE3 features are unchanged.

Matrix SDK 0.19.1 requires BLAKE3 1.8.7. BLAKE3 1.8.7 removes its `arrayref`
dependency after the crate owner's account was compromised. Advancing the
Starlark pin keeps Matrix's supported minimum instead of lowering it. The
compatible `pagable 0.4.2` release already accepts BLAKE3 1.8 and is selected
normally by the workspace lockfile.

Starlark uses `blake3::Hasher` for heap identifiers. The BLAKE3 1.8.4 change to
its optional `traits-preview` implementation does not cross a Starlark public
API or alter its use of the inherent hasher methods. Execpolicy behavior tests
exercise the unchanged Starlark interpreter against the shared dependency.

`BUILD.bazel` exposes this local package to Bazel. `Cargo.toml.orig` and
`Cargo.lock` are preserved upstream package files; workspace resolution uses
the root `codex-rs/Cargo.lock`.

Sources:

- https://crates.io/crates/starlark/0.14.2
- https://github.com/BLAKE3-team/BLAKE3/releases/tag/1.8.7
- https://github.com/BLAKE3-team/BLAKE3/releases/tag/1.8.4

Published `.crate` SHA-256 (verified against the crates.io index):

`9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`
