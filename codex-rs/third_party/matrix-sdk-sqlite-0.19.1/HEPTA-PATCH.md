# matrix-sdk-sqlite 0.19.1 compatibility patch

Source: https://static.crates.io/crates/matrix-sdk-sqlite/matrix-sdk-sqlite-0.19.1.crate

Official archive SHA-256: `8d4271e06d52a17bc6ec39b5a2985b65dcced737969fac3678967783656edb34`.

Both published manifests select `rusqlite 0.41`, which uses the actual
`libsqlite3-sys 0.39` / SQLite 3.54 implementation shared with product SQLx.
The original `limits`, `fallible_uint`, and `cache` features are retained.
This preserves the previously carried rusqlite compatibility patch while
advancing the Matrix implementation and its complete migration set to 0.19.1.
Both manifests also raise vodozemac's floor to 0.11.2.

Cipher import and export now run on Tokio's blocking pool. The SDK already
opens its four independent SQLite stores concurrently, but synchronous PBKDF2
inside their async futures serialized the derivations on the polling thread.
The original cipher algorithms, salts, formats and 200,000-round password
derivation remain unchanged. The async caller still reads and saves the cipher
record; blocking tasks receive only owned cipher bytes and the zeroizing secret.
Cancellation aborts queued work. A running calculation cannot be interrupted,
but it cannot write to SQLite, and an unclaimed result is dropped normally.
The original high-entropy-passphrase migration is retained. The manifests now
explicitly request Tokio's `rt` feature for this blocking-task API.

The release archive omits its repository license file. LICENSE is copied
from upstream commit b18166c68bb958a21f0bca8b2d8320cb53583362:
https://raw.githubusercontent.com/matrix-org/matrix-rust-sdk/b18166c68bb958a21f0bca8b2d8320cb53583362/LICENSE

The published standalone Cargo.lock is omitted; product Cargo and Bazel
locks govern the selected graph. This dependency is excluded from product
workspace membership and materialized by Bazel's `@crates` generator.
All first-party features remain included in the original cargo-deny gate.
No advisory ignore or license allowlist is changed.
