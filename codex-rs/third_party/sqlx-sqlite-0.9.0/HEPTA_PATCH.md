# SQLx SQLite compatibility patch

Source: crates.io `sqlx-sqlite 0.9.0`, unchanged Rust sources and migrations.
The normalized and original manifests change only `libsqlite3-sys` from
`>=0.30.1, <0.38.0` to exactly `0.38.2`.

Matrix SDK 0.19.1 uses rusqlite 0.40.2 / libsqlite3-sys 0.38.2. Cargo permits
only one `links = "sqlite3"` dependency. Align SQLx upward rather than changing
Matrix's encryption/store implementation or downgrading its rusqlite APIs.
The workspace's direct native dependency is pinned to the same version.

The selected bundled SQLite is 3.53.2, newer than the previous 3.51.3 that
contained the WAL-reset corruption fix. Do not remove the existing shared
SQLite-constructor policy or switch this graph to a system SQLite silently.

Review surface: native API compatibility, SQLx storage/reopen/crash tests,
Matrix state/crypto/event-cache migration, and the final dependency audit.
No claim of a full SQLx upstream test-suite pass is implied by this patch.
