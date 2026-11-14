# matrix-sdk 0.19.1 compatibility patch

Source: https://static.crates.io/crates/matrix-sdk/matrix-sdk-0.19.1.crate

Official archive SHA-256: `2afc652a144822f6fbe24084e08bc59cb483fd0b504396d492131dec0749396e`.

The real event-handler context map now uses maintained `anymap3 1.1.0`.
Its `std` map backend is selected explicitly (the Matrix SDK already requires
std), and `CloneAny` uses the new crate's public root export. The native map
retains `Clone + Send + Sync` values and the WASM map retains
`Clone` values. The upstream API's insertion, replacement, type separation,
and cloned handler-context behavior are preserved. No package is renamed to
conceal an old implementation.

Both published manifests also raise vodozemac's floor to 0.11.2. Other Matrix
SDK behavior and features remain the official 0.19.1 implementation.

The release archive omits its repository license file. LICENSE is copied
from upstream commit b18166c68bb958a21f0bca8b2d8320cb53583362:
https://raw.githubusercontent.com/matrix-org/matrix-rust-sdk/b18166c68bb958a21f0bca8b2d8320cb53583362/LICENSE

The published standalone Cargo.lock is omitted; product Cargo and Bazel
locks govern the selected graph. This dependency is excluded from product
workspace membership and materialized by Bazel's `@crates` generator.
All first-party features remain included in the original cargo-deny gate.
No advisory ignore or license allowlist is changed.
