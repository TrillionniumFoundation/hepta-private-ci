# Hepta compatibility patch

This directory is the crates.io source package `matrix-sdk-sqlite 0.19.1`,
except for one dependency compatibility patch: `rusqlite` uses `0.39.0`
instead of upstream `0.40.2`. The upstream `limits`, `fallible_uint` and `cache`
features remain enabled.

The selected release uses `libsqlite3-sys 0.37`, already required by Hepta's
SQLx 0.9 workspace for the SQLite WAL-reset corruption fix. Cargo permits only
one native `sqlite3` links crate in a dependency graph; upstream rusqlite 0.40
would instead require `libsqlite3-sys 0.38`.

No Matrix SDK SQLite source or migration is changed. The 0.19 upstream
migrations rebuild its derived event cache at schema transitions 15 and 18.
Crypto schema 18 consolidates pending key requests, and schema 19 clears the
SDK's Sliding Sync position; state migrations add persisted global profiles.
Existing account, encryption keys and ordinary passphrase store opening are
retained. The new high-entropy key option is not enabled.

Hepta's authoritative durable inbox and sync checkpoint live in the separate
`matrix_1.sqlite3` store. The adapter retains its existing `matrix-sdk-0.18`
directory name so it reopens and migrates the existing SDK state, crypto and
session data, and clears the SDK's own sync token before restoring a session.
Its explicit Hepta checkpoint remains authoritative.

The adapter's `sdk_store_upgrade` integration test opens actual encrypted
0.18 databases, restores the old session twice, compares account identity and
device trust, decrypts an old Megolm event, and checks that the separate Hepta
inbox and cursor stay unchanged. The fixture's event and media caches are empty;
this test does not establish migration of populated cache contents. Fixture
provenance and regeneration instructions live alongside the test data.

This is a forward upgrade. Running the old 0.18 binary against migrated stores
is unsupported: that store code does not reliably reject newer schema versions,
while event identifiers and pagination-token serialization have changed. Room
read-receipt state also changes from an array to an object with `items` and
`capacity`; the new reader accepts old data, but the old reader does not accept
new writes. The SDK event cache is rebuildable; SDK state, crypto keys, sessions
and the Hepta owner store are not disposable cache. Rewinding an old snapshot would also
rewind trust, revocations, fences or external-session state and is not a
qualified rollback. Any rollback must preserve those current authorities and
be independently implemented and verified.

`BUILD.bazel` exposes upstream SQL migration inputs to Bazel.
`Cargo.toml.orig` and `Cargo.lock` are preserved upstream package files;
workspace resolution uses the root `codex-rs/Cargo.lock`.

Sources:

- https://crates.io/crates/matrix-sdk-sqlite/0.19.1
- https://github.com/matrix-org/matrix-rust-sdk/releases/tag/0.19.0

Published `.crate` SHA-256 (verified against the crates.io index):

`8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`
