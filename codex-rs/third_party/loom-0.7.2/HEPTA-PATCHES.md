# Hepta private pin-utils backport

Private std::pin::pin! substitution; no additional allocation/API change intended. Original futures=[pin-utils] retained and formerly implicit pin-utils feature kept as an explicit empty compatibility alias, without the pin-utils crate. Explicit MSRV1.68; workspace toolchain remains1.95.0. Requires actual review and CI.

The official archive checksum and exact edits are recorded in HEPTA-PATCH-PROVENANCE.json. Cargo.toml and Cargo.toml.orig carry the same dependency/feature change. All other archive files, including the license and any historical vendored Cargo.lock, are preserved. The workspace Cargo.lock is the dependency authority. No crate version is advanced.
