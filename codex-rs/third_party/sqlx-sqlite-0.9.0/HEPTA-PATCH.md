# sqlx-sqlite 0.9.0 compatibility patch

Source: https://static.crates.io/crates/sqlx-sqlite/sqlx-sqlite-0.9.0.crate

Official archive SHA-256: `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`.

Both published manifests admit the `libsqlite3-sys 0.39` API and require
its security-fixed SQLite 3.54 source. The upper bound remains below 0.40 so
future native API changes require a new compatibility review. The existing
bundled/unbundled and optional SQLite feature forwarding is unchanged.
All SQLx Rust driver code remains the official 0.9.0 implementation; the
product's direct native SQLite requirement selects the real 0.39 release.
No crate version, `links` key, or bundled C source version is relabelled.

The complete upstream Apache-2.0 and MIT license files are retained.

The published standalone Cargo.lock is omitted; product Cargo and Bazel
locks govern the selected graph. This dependency is excluded from product
workspace membership and materialized by Bazel's `@crates` generator.
All first-party features remain included in the original cargo-deny gate.
No advisory ignore or license allowlist is changed.
