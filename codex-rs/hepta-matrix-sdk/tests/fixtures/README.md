# Matrix 0.18 encrypted storage fixture

`matrix_0_18.json` contains ordinary synthetic stores created by the official
Matrix SDK 0.18 implementation, with the product's previous SQLite and imbl
compatibility patches. All session values and encryption keys are disposable
test data. No user data or external homeserver is used.

The fixture records the actual resolved source versions, generator SHA-256,
and each SQLite SQL dump's SHA-256. The verbatim historical generator is
retained as `matrix_0_18_generator.rs.txt`; rename it to `src/main.rs` in a
standalone Cargo package to regenerate a fixture with fresh test keys.
After a successful generator run, SQLite WALs were checkpointed; Python's
SQLite `iterdump()` and `PRAGMA user_version` preserve the database content.
The current SQLx driver imports these dumps, and the production Matrix
client performs schema upgrades and restores the existing encrypted identity.

The generator is an archived fixture source, not a Cargo integration test.
The fixture was generated with Rust 1.96.1 and two Cargo build jobs. Its
standalone dependencies were matrix-sdk =0.18.0 (default features disabled;
e2e-encryption and sqlite enabled), libsqlite3-sys =0.37.0 (bundled),
tokio (macros and rt-multi-thread), and serde_json. The previous product
matrix-sdk-sqlite 0.18.0 and imbl 6.1.0 patches were applied unchanged.
