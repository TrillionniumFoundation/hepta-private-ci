# Hepta Native

`apps/hepta-native` now contains the Rust desktop host for the `ui.native`
boundary. The historical JavaScript files remain temporarily as compatibility
and regression fixtures; production development is Rust-first.

## Selected native stack

- Rust 1.95
- eframe/egui 0.36.2 for the desktop window and rendering
- AccessKit through eframe for native accessibility semantics
- existing loopback-only `codex-hepta-native-gateway` as the runtime read side
- OS keychain through the repository's `codex-keyring-store`
- Ed25519 signed, final-payload-bound `PlatformGrantV1` for platform effects
- Ed25519 signed update manifests plus predecessor/package SHA-256 binding
- separate `hepta-native-updater` helper for restart and rollback

The supported target matrix is frozen in [PLATFORM_MATRIX.json](PLATFORM_MATRIX.json).

## Runtime correctness

Operation identity is the tuple
`(session_id, session_generation, operation_id)`. Session identity is stable
for one backend generation and changes when the backend generation changes.

Before invoking a platform adapter, the shell writes and fsyncs a durable
`dispatching` record. A crash after that point never causes an automatic
replay. The next request executes the adapter's reconciliation path and remains
`indeterminate` when the OS cannot provide a trustworthy terminal observer.

Terminal decisions are durable. Reusing an operation key with a changed action
or final payload is rejected.

## Platform effects

Every effect requires both:

1. a one-shot user confirmation in the current native session; and
2. an independently signed grant that binds the session/generation, operation,
   action, resource digest and final payload digest.

The shell never mints those grants. If the pinned platform grant key is absent,
effects fail closed.

Trust roots may be provisioned either by environment for qualification or by
the OS keychain:

- `HEPTA_NATIVE_PLATFORM_GRANT_PUBLIC_KEY_B64`
- `HEPTA_NATIVE_PLATFORM_GRANT_SIGNER_ID`
- `HEPTA_NATIVE_PLATFORM_GRANT_KEY_ID`

The keychain account is `hepta.native/platform-grant-public-key-v1` and stores
JSON with `signer_id`, `key_id`, and `public_key_b64`.

## Updates

Update manifests bind platform, architecture, backend protocol, package digest,
predecessor digest, selector, generator principal and validity window. The
selector and generator must differ and both values are covered by the signature.

Update trust can be supplied with:

- `HEPTA_NATIVE_UPDATE_PUBLIC_KEY_B64`
- `HEPTA_NATIVE_UPDATE_KEY_ID`

or keychain account `hepta.native/update-public-key-v1`.

Set `HEPTA_NATIVE_REQUIRE_OS_CODESIGN=1` in release builds to additionally
require macOS codesign/notarization checks or Windows Authenticode. Linux uses
the pinned update manifest signature as the repository-level package trust root.

The helper keeps a predecessor backup, starts the replacement, waits for a
post-update-ready marker, and restores the predecessor when readiness is not
observed.

## Development

```bash
cargo fmt --manifest-path apps/hepta-native/Cargo.toml -- --check
cargo test --manifest-path apps/hepta-native/Cargo.toml --all-targets
cargo clippy --manifest-path apps/hepta-native/Cargo.toml --all-targets -- -D warnings
cargo run --manifest-path apps/hepta-native/Cargo.toml -- --self-test
cargo run --manifest-path apps/hepta-native/Cargo.toml
```

The application expects the existing read-only native gateway at
`http://127.0.0.1:7373`. A successful process launch, desktop-open request, or
notification dispatch is not promoted into terminal success when the OS does
not expose a trustworthy final observer.
