# Keyring 3.6.3 encrypted synchronous backend patch

## Upstream identity

- Upstream: <https://github.com/hwchen/keyring-rs>
- Release archive: <https://static.crates.io/crates/keyring/keyring-3.6.3.crate>
- Archive size: 67,500 bytes.
- Archive SHA-256: `eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`.
- This digest matches the registry checksum in the parent Cargo.lock.
- License: upstream MIT OR Apache-2.0; both original license files are retained.
- Cargo cache bookkeeping files are omitted. Upstream source, examples, and tests
  are retained, with repository rustfmt applied to imported Rust files.

## Reason for the patch

The upstream `crypto-rust` feature references both optional Secret Service
implementations. Cargo can retain unused optional dependencies mentioned by weak
features in its lockfile and metadata, even when they are absent from the compiled
tree: <https://github.com/rust-lang/cargo/issues/10801>. Selecting only the
synchronous backend therefore did not remove the old async dependency family
from this workspace's actual all-target lock.

The workspace uses the new `crypto-rust-sync` feature in both keyring-store and
rmcp-client. It forwards Rust cryptography only to `dbus-secret-service`.
The existing upstream features remain available for compatibility. Both session
creation sites treat the new feature as encrypted `EncryptionType::Dh`; errors
are returned without retrying a plaintext session. Combining the new feature
with the async backend is a compile error.

Removing cryptography is not an acceptable substitute: upstream selects
`EncryptionType::Plain` when no cryptography feature is active.

## Cargo and Bazel parity

The repository excludes `codex-rs/third_party` workspace targets in .bazelignore.
Its `@crates` resolver materializes path patches as external dependencies, including
their resolved features. Do not add a workspace `codex_rust_crate` target here:
its dependency table and feature expansion do not apply to these external crates.
Linux uses native keyutils plus the synchronous persistent store; macOS and Windows
retain their existing native stores. FreeBSD/OpenBSD select the synchronous store.
The resolver-generated Cargo.lock and MODULE.bazel.lock belong in the same change;
check the actual generated external target when validating Bazel parity.

This patch does not select a backend on its own, introduce mobile support, or
change the upstream fallback behavior on unsupported targets. Mobile and native
Secret Service runtime qualification require separate evidence. Local dependency
resolution or compilation alone is not evidence of a successful OS credential
round trip or completed Windows/macOS CI.

## Removal

Remove this path patch only after an upstream feature contract can select the
encrypted synchronous store without the unused async lock closure, and both
Cargo and Bazel resolve and compile the replacement on supported platforms.
