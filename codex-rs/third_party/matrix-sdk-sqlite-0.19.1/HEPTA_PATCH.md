# Matrix SQLite 0.19.1 native links compatibility candidate

The full published crate is retained. Its original archive is
https://static.crates.io/crates/matrix-sdk-sqlite/matrix-sdk-sqlite-0.19.1.crate
with SHA-256
8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34.
It records upstream commit b18166c68bb958a21f0bca8b2d8320cb53583362.

Only the rusqlite constraint changes: upstream 0.40.2 becomes exactly 0.39.0
in both manifests. Upstream limits, cache and fallible_uint features are
retained. Rusqlite 0.39 uses libsqlite3-sys 0.37, matching the existing SQLx
0.9 graph. Upstream rusqlite 0.40.2 requires libsqlite3-sys 0.38, which cannot
coexist in a Cargo graph with the same native sqlite3 links identifier.

No Rust storage implementation or SQL migration file is modified.
BUILD.bazel exposes every migration SQL file to compile-time includes.
LICENSE is the exact Apache license from the recorded upstream commit.
The original nested Cargo.lock is upstream package material; the active
Hepta Cargo.lock must be regenerated and checked for a single SQLite links
package.

This is a real upgrade to the 0.19.1 backend. Upstream intentionally rebuilds
the event cache after changing stored event identifiers and cursor encoding.
The change must not be described as persistence-neutral. Hepta retains the
existing SDK directory and checks identity keys, session, custom state and its
separate authoritative cursor/inbox/outbox across an actual 0.18-to-0.19 reopen.
The human passphrase API is preserved; it is not replaced by the new
high-entropy-passphrase API.

Rusqlite API inspection alone is not a compilation or migration pass. The
complete workspace, upstream store tests and cross-version fixture gate must
run on the candidate before landing.
