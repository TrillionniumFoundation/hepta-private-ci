# AWS credentials-login compatibility patch

This directory preserves the crates.io `aws-config` 1.12.0 package under its
Apache-2.0 license. `HEPTA_SOURCE.json` records the original archive checksum,
Git source revision, and every original file checksum. `Cargo.toml.orig` remains
upstream source, while the normalized `Cargo.toml` is the build manifest.

The local patch advances P-256 from 0.13.2 to 0.14.0 so Cargo resolves the fixed
RustCrypto crypto-bigint line. AWS credentials-login stays enabled. The only
runtime adaptation uses the renamed SEC1 conversion trait and rand 0.10's
fallible OS-seeded StdRng. ES256 remains randomized; RNG failure is propagated
as a login error. Existing JWK/PEM tests remain, with a signature verification
and tamper rejection regression added. No advisory ignore is added.

This is a Hepta compatibility patch, not an upstream AWS release. Remove it when
a reviewed upstream AWS package uses a fixed cryptography dependency graph.
The workspace Cargo.lock and MODULE.bazel.lock identify the actual graph.

`HEPTA-repository-format.patch` records the separate, mechanical repository
Rust formatting pass. Apply the compatibility patch first, then formatting.
The manifest records both patch hashes and final original-file hashes.
