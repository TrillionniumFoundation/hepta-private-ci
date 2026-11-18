# SQLx SQLite dependency-bound backport

This is the published sqlx-sqlite 0.9.0 crate, not a new upstream release or a copy of SQLx main. The archive SHA-256 matches the existing workspace Cargo.lock registry checksum. All 57 archive files, including both licenses, Cargo.lock, Cargo.toml.orig and .cargo_vcs_info.json, are retained.

The sole upstream-file edit is the normalized Cargo.toml libsqlite3-sys bound from `>=0.30.1, <0.38.0` to `>=0.30.1, <0.41.0`. This follows upstream commits 10462fa4414c6c7f1ed1d39bb31678e3b726878c (0.39 support) and b7966fab5b28e92b09171df0a5b9161a175e914c (0.40 support). No Rust, SQL, linkage features or constructor safety lint changes are included. See HEPTA-PROVENANCE.json for every original file hash.

The root pins libsqlite3-sys 0.40.0 and the existing Matrix sqlite adapter pins rusqlite 0.43.0. Qualification must establish a single sqlite3 links graph, bundled compilation, and actual SQLx/Matrix consumer tests. A successful resolver alone does not establish ABI or migration compatibility. The bundled crate Cargo.lock is upstream provenance, not the workspace resolution. Chrono retirement and rmcp upgrades are separate open work.
