# Hepta private pin-utils backport

Upstream Hyper #4023 pin-only source and feature change, normalized into both manifests. Uses the existing tokio::pin! macro; no new dependency, feature, API or MSRV increase.

The official archive checksum and exact edits are recorded in HEPTA-PATCH-PROVENANCE.json. Cargo.toml and Cargo.toml.orig carry the same dependency/feature change. All other archive files, including the license and any historical vendored Cargo.lock, are preserved. The workspace Cargo.lock is the dependency authority. No crate version is advanced.
