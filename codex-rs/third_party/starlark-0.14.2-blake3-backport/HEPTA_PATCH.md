# Starlark 0.14.2 BLAKE3 compatibility backport

The original published crate and omitted Apache license are retained in the source-only commit recorded by HEPTA-PATCH-PROVENANCE.json. This patch changes only the normalized and original manifest BLAKE3 constraints from exact 1.8.2 to exact 1.8.7. It preserves the original default/rayon/std/traits-preview features, all Rust source, the build script and Starlark API.

Matrix store encryption 0.19.1 requires BLAKE3 1.8.7. Starlark upstream's workspace at 4395d80da451d94f60fe29f0d4dd38ee585ff062 permits the 1.8 series. This backport selects exactly 1.8.7 while retaining the published 0.14.2 Rust implementation. The only Starlark use is the StrongHash adapter's Hasher update/finalize API; compatibility still requires actual execpolicy tests on the final shared lock.

The Bazel wrapper preserves upstream compiler-channel detection through its original build.rs. No dev-test dependency is added to the production graph. This candidate reuses only the wrapper pattern from an earlier repository change, not that change's lockfiles or test results. All actual resolver failures and validation receipts are retained separately.
