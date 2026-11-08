# Published Matrix SDK 0.19.1 with the upstream anymap3 fix

The full published crate is retained. Its original archive is
https://static.crates.io/crates/matrix-sdk/matrix-sdk-0.19.1.crate
with SHA-256
2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e.
The package records upstream commit
b18166c68bb958a21f0bca8b2d8320cb53583362.

The event-handler change is the actual upstream replacement of anymap2 with
anymap3, from commit
https://github.com/matrix-org/matrix-rust-sdk/commit/9c5fdd2cf5be1b7b8b20541e56d7a109db968534.
The crate uses anymap3 1.1.0 with its std feature and the maintained CloneAny
implementation. Native contexts remain Send + Sync; the existing wasm context
type remains unchanged in its thread-safety requirements.

Handwritten vendor changes are limited to Cargo.toml, Cargo.toml.orig and
src/event_handler/mod.rs. BUILD.bazel declares the upstream documentation
include files. LICENSE is the exact Apache license from the recorded upstream
commit, which the crates.io package did not include.

The package's original Cargo.lock is retained as upstream package material.
Hepta builds use the repository Cargo.lock generated after applying this
patch; that active graph must contain anymap3 and no anymap2.

Matrix 0.19.1 requires Rust 1.96. Its TLS provider feature must be enabled
explicitly by Hepta, preserving the HTTPS support formerly activated
unconditionally by Matrix 0.18. No encryption or persistence feature is removed.

This patch is a candidate until the recorded complete-workspace tests,
old-store migration, Bazel lock generation and unchanged cargo-deny policy pass.
