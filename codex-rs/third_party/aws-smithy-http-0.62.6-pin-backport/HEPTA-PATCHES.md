# Hepta private pin-utils backport

Private adaptation of the upstream AWS pin-only change to this exact older archive. The original mutable Pin binding is retained where data()/as_mut() requires it; all other source, versions and APIs remain unchanged.

The official archive checksum and exact edits are recorded in HEPTA-PATCH-PROVENANCE.json. Cargo.toml and Cargo.toml.orig carry the same dependency/feature change. All other archive files, including the license and any historical vendored Cargo.lock, are preserved. The workspace Cargo.lock is the dependency authority. No crate version is advanced.
