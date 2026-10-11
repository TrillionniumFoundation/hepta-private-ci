# Hepta compatibility patch

This directory is the unmodified crates.io source package
`matrix-sdk-sqlite 0.18.0`, except for one dependency compatibility patch:

- `rusqlite` is advanced from `0.37.0` to `0.39.0`;
- its `cache` and `fallible_uint` features are explicit, because 0.39 gates
  APIs and conversions used by matrix-sdk-sqlite behind those features.

Both versions expose the APIs used by `matrix-sdk-sqlite 0.18.0`. The newer
release selects `libsqlite3-sys 0.37`, which is already required by Hepta's
SQLx 0.9 workspace for the SQLite WAL-reset corruption fix. Cargo does not
allow the upstream `libsqlite3-sys 0.35` and Hepta's `0.37` to coexist because
both link the native `sqlite3` library.

No Matrix SDK source or persistence behavior is changed. The workspace builds
and tests this crate through the normal `matrix-sdk 0.18.0` dependency graph.
