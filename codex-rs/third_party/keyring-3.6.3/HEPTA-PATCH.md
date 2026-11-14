# Keyring 3 credential compatibility with zbus 6

Source: the official keyring 3.6.3 crates.io release, archive SHA-256
`eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`.
Upstream tag v3.6.3 resolves to commit
`315cbdf6c6a9153d8c9f88b56568f29862d3e39d`.
All published Rust sources and both licenses are retained unchanged.
The standalone upstream Cargo lock is omitted; the product lock resolves
the dependencies used by this application.

Both published manifests change the Secret Service dependency to the exact
official `6.0.0-rc.1` release and zbus to `6.3.0`. Secret Service 6 is
currently an upstream release candidate, explicitly pinned here. Its source
tag is `34156ba24360753f68a1b59aaf9e40a6055299f4`.
The package MSRV is updated to the dependencies' Rust 1.89 minimum; the
product continues using Rust 1.96.1.

The existing `async-io` feature name continues to select the non-Tokio
backend through zbus 6's `default-rt` feature. The Tokio, RustCrypto,
OpenSSL, Linux keyutils/persistent, Windows, macOS and BSD feature entry
points remain available. Credential attributes, collection lookup and
error handling are the unchanged keyring 3 implementation.

zbus 6 incorporates the formerly separate zvariant, zvariant_derive and
zbus_names crates. Keeping the existing keyring interface avoids changing
credential identity or platform behavior while removing those unmaintained
dependencies. No advisory ignore or license policy is added.

This dependency is excluded from product workspace membership, as with
the ZIP compatibility patch. Bazel materializes it through `@crates`.
Remove the patch after a compatible upstream keyring release adopts zbus 6.

Sources:

- https://crates.io/crates/keyring/3.6.3
- https://github.com/open-source-cooperative/secret-service-rs/releases/tag/v6.0.0-rc.1
- https://z-galaxy.github.io/zbus/upgrading-to-6.html
