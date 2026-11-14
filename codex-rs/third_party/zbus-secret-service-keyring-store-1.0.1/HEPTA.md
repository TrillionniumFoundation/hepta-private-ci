# Existing Keyring backend on maintained zbus

This document retains the original import and dependency-patch record. The current
checkout also includes the repository formatting follow-up described below.


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

## Repository formatting follow-up (2026-11-14)

The normal repository formatter changed 5 Rust files.
HEPTA-FORMATTING-PROVENANCE.json binds every affected path to its exact Git
object, mode, size and SHA256 before and after formatting. The comparison uses
c2130629037b342e6e48154867b65acc8fc82434 as the input identity.

Import targets, aliases, visibility and attached attributes are retained.
Comments and non-import literals are retained; the other reviewed changes are
layout, trailing punctuation, single-expression block layout and same-order
derive grouping. Existing minimal dependency patches, upstream README files
and license bytes are retained. This record does not claim a new runtime test
result or a successful full-repository formatting check.
