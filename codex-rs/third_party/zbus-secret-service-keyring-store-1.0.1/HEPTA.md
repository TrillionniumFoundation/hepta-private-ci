# Existing Keyring backend on maintained zbus

The original `zbus-secret-service-keyring-store 1.0.1` registry archive has
SHA-256 `74801d001b9e7729adb4f1825b67b398185fed424749aa3d8bacf70417137d9a`,
identical to the original project Cargo.lock checksum. All source, examples,
README and MIT/Apache license files are retained.

Two dependency constraints select Secret Service 6 and zbus 6. The only Rust
source changes are the two `OwnedObjectPath` imports, which now use zbus's root
exports. The package version and credential identity remain `1.0.1`. The root
Bazel alias points to `@crates//:zbus-secret-service-keyring-store-1.0.1`, the
native rules_rs library generated from this local Cargo.toml with version
`1.0.1`. Cloud evidence checks that actual library's version, dependency edges
and `crypto-rust` feature before building it; the store uses `CARGO_PKG_VERSION`
in its identifier. Keyring 4.2's callers, store behavior,
encrypted backend and all 21 original tests are unchanged. The existing one
interactive ignored test is retained and is reported as unexecuted.

The full Cargo suite runs against a real private session bus and Gnome Keyring
in the project cloud. The existing three-platform consumers and original
security gates remain required. The registry packaging Cargo.lock,
Cargo.toml.orig, `.gitignore` and VCS marker are omitted in favor of the project
generated graph and this documented patch. No advisory suppression or backend
feature removal is included. Source-only review is not production qualification.
