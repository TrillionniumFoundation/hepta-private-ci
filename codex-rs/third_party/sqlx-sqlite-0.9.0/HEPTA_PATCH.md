# SQLx SQLite 0.9.0 compatibility candidate

The official crate archive and both licenses are retained and bound by HEPTA-PATCH-PROVENANCE.json. Only the libsqlite3-sys constraints in Cargo.toml and Cargo.toml.orig change: the upstream range >=0.30.1, <0.38.0 becomes exactly 0.39.1. All upstream Rust, SQL, tests, and other archive bytes remain unchanged. BUILD.bazel wires this path crate through the repository's existing codex_rust_crate rule.

libsqlite3-sys 0.39.1 bundles SQLite 3.54.1, covering RUSTSEC-2026-0459 for the bundled SQLite graph. The shared graph must resolve one sqlite3 links owner alongside rusqlite 0.41.1. SQLCipher is a separate feature and is not qualified by this declaration.

This is a compatibility candidate. Dependency audit and resolution do not establish SQLx durable state behavior, Matrix encrypted migration, restart, retained ciphertext decryption, replay rejection, or deployed acceptance. Those require actual same-source owning tests; deadlines and durability guards are unchanged.

The original archive license entries remain byte-identical. Full upstream license texts are attached as `UPSTREAM-LICENSE-APACHE`, `UPSTREAM-LICENSE-MIT`, fetched from the exact .cargo_vcs_info.json commit and SHA-256 bound in the provenance record.
