# SQLx native SQLite alignment

This is the official SQLx SQLite 0.9.0 crate. Only the two manifest constraints for
`libsqlite3-sys` change, from `>=0.30.1, <0.38.0` to exact `0.38.2`. Matrix SDK
0.19.1 uses rusqlite 0.40.2, whose native dependency is 0.38.2. Cargo permits one
`sqlite3` links package in the product graph. The workspace selects that same
version explicitly.

SQLx Rust implementation is unchanged apart from repository formatting. All 57
official members are accounted for in the qualification provenance. The original
state consumer, Matrix storage migration and Bazel checks remain required; the
manifest change alone is not a compatibility result. No advisory policy is changed.
