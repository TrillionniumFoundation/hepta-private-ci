# matrix-sdk-sqlite 0.19.1 compatibility patch

Source: https://static.crates.io/crates/matrix-sdk-sqlite/matrix-sdk-sqlite-0.19.1.crate

Official archive SHA-256: `8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`.

Both published manifests select `rusqlite 0.41`, which uses the actual
`libsqlite3-sys 0.39` / SQLite 3.54 implementation shared with product SQLx.
The original `limits`, `fallible_uint`, and `cache` features are retained.
This preserves the previously carried rusqlite compatibility patch while
advancing the Matrix implementation and its complete migration set to 0.19.1.
Both manifests also raise vodozemac's floor to 0.11.2.

Store-cipher preparation now runs on a Tokio blocking worker. The async
connection owner still reads and writes the same `cipher` key, and only writes
a pending export after successfully joining the worker. Password derivation,
key import/export, the high-entropy migration, and the existing test-only
fast-export branch are unchanged. Started cipher work may outlive a cancelled
async owner, but has no database connection or path and cannot write the store.

An optional typed observer records eight fixed atomic slots for the four store
roles and their existing cipher workers. A private task-local scopes each open;
only the small observation handle crosses the existing worker boundary. Store
operations, migrations, cipher algorithms, and public errors are unchanged.
Snapshots are independent last-entered observations, not timing or success
proofs; started workers can update them after the async owner is cancelled.
The Hepta wrapper reads them only at its existing diagnostic report sites.

The release archive omits its repository license file. LICENSE is copied
from upstream commit b18166c68bb958a21f0bca8b2d8320cb53583362:
https://raw.githubusercontent.com/matrix-org/matrix-rust-sdk/b18166c68bb958a21f0bca8b2d8320cb53583362/LICENSE

The published standalone Cargo.lock is omitted; product Cargo and Bazel
locks govern the selected graph. This dependency is excluded from product
workspace membership and materialized by Bazel's `@crates` generator.
All first-party features remain included in the original cargo-deny gate.
No advisory ignore or license allowlist is changed.
