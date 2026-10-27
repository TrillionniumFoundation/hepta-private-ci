# keyring 3.6.3: maintained zbus transport without a public API migration

This directory is the published `keyring 3.6.3` source, licensed under MIT OR
Apache-2.0. Both upstream license files and `Cargo.toml.orig` are retained.

Official source:
https://static.crates.io/crates/keyring/keyring-3.6.3.crate

Original archive SHA-256:
`eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`.

Every original Rust source file is byte-identical to that archive. The only
production change is in the normalized manifest: Linux/FreeBSD/OpenBSD zbus
requirements advance from 4 to 6.1; the existing `async-io` feature name selects
zbus 6's `default-rt`; the declared MSRV becomes 1.89 to reflect zbus 6.1. The
`tokio`, native, sync/async persistent, crypto and platform features remain.
The paired patch to `secret-service 4.0.0` is required. A keyring-only patch
would still retain zbus 4 through secret-service.

The Entry, CredentialApi, Error, mock backend, credential attributes, password
and binary encoding, native platform implementations, deletion and error
mapping have not changed. macOS/iOS security-framework and Windows dependency
requirements and features have not changed. `BUILD.bazel` supplies the normal
workspace crate rule after the parent graph is regenerated. Its explicit
feature select follows this workspace's configured Linux/macOS/Windows backend
choices; `CARGO_PKG_VERSION=3.6.3` preserves the labels that embed that value.
The crate macro does not infer local source features from the Cargo dependency
list, so leaving this select empty would incorrectly choose the mock backend.

## Existing upstream behavior retained

The published `KeyutilsPersistentCredentialBuilder::build` constructs
`SsCredential`, despite the surrounding composite-store documentation. This
patch preserves that behavior. The explicit `KeyutilsPersistentCredential`
implementation remains available and is separately exercised in the isolated
regressions. Changing the default builder would also alter empty-secret and
attribute semantics, and is not hidden inside this dependency repair.

## Verification boundary

The candidate's isolated GNOME Secret Service suite covers both actual backends,
cross-backend stored credentials, native/composite cache refill and rollback in
fresh user namespaces, plain/DH wire transport, no-entry/ambiguous/encoding
errors, concurrency, and real daemon restarts. The actual `codex-keyring-store`
crate is compiled and exercised for its Option/bool API. The local kernel reports
EOPNOTSUPP for the optional namespace persistent register; session-cache plus
Secret Service persistence is covered, but kernel-register persistence is not.

Full workspace Cargo/Bazel resolution, the unchanged advisory scan, application
login/OAuth regressions and macOS/Windows execution remain parent integration
gates. Run upstream keyring tests only against a dedicated test keystore. The
production candidate does not change dependency policy or introduce ignores.
