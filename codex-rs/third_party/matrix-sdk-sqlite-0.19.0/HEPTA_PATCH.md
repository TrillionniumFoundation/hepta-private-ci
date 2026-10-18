# Upstream Matrix SQLite store 0.19.0

Source: the official crates.io `matrix-sdk-sqlite` 0.19.0 archive, SHA-256
`fc72eaeae8a98dad0fd892607558d3bd40fe02575d522d4642f7c45631f738c9`.

The only upstream file changes are in the published and original Cargo
manifests: `rusqlite` is advanced to the compatible 0.39 release so this store
and the workspace SQLx 0.9 dependency use the same `libsqlite3-sys` 0.37 native
SQLite library. Existing rusqlite features and all upstream SQL, transactions,
WAL settings, migrations, encryption and state-store algorithms are preserved.

The Cargo-derived rules_rs repository includes every upstream migration in
the generated crate's `compile_data`; no separate vendor workspace target
or second SQLite crate identity is created.
Remove this patch when the upstream store supports the workspace's SQLite
native-library family directly.
