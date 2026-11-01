# Matrix SDK crypto: upstream identity-strategy security fix

Published 0.18.0 archive SHA-256:
`c54afd2a326f51c13a6ad44ec86315a688fffeb3f1e287fb343e0e1836a3bdaf`.
The upstream Apache license is retained from the package's recorded source
commit `1c44fb66214667c6d00acaf72ab592493653708b`.

This applies the literal upstream fix and its regression from
<https://github.com/matrix-org/matrix-rust-sdk/commit/01b45b51299821ab03fecf46741392780f118d49>.
When IdentityBasedStrategy sees a device owner without cross-signing keys, both
code paths withhold the key with `WithheldCode::Unverified` instead of panicking.
The upstream regression covers unsigned devices and missing identities under
both trusted-device and identity-based policies. It does not weaken encryption
trust decisions or turn encryption off.

The compatible 0.18 API is retained because published 0.19 requires a newer Rust
toolchain than this repository's pinned Rust 1.95. This is a documented local
backport, not a claim that the registry's unpatched 0.18 release is safe.

