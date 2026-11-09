# Matrix SQLite 0.19.1 compatibility candidate

The official archive and upstream license are bound by HEPTA-PATCH-PROVENANCE.json. That retained import record describes the original manifest-only compatibility patch: the two rusqlite constraints changed from 0.40.2 to exactly 0.39.0, retaining upstream limits, fallible_uint and cache features. This preserves the existing libsqlite3-sys 0.37 link shared with SQLx 0.9. The later Rust change below is separate from that historical import; SQL migration files remain unchanged.

This SDK upgrade performs real storage migrations: crypto state reaches version 19, state reaches version 16, and event cache reaches version 18 with upstream cache resets. Hepta retains the matrix-sdk-0.18 directory as its existing data identity, its human passphrase API, its own authoritative sync cursor/inbox/outbox, and its production five-second startup bound. Old SDK binaries must not reopen stores after migration; this change does not provide reverse migration or claim lossless binary rollback. Recovery requires an independently retained, consistent pre-upgrade store backup.

Native qualification must create encrypted stores and old Olm/Megolm ciphertext with the original 0.18 graph, then reopen through the candidate production API and decrypt with the existing persisted sessions. Same-version restart, matching public keys, a compilation pass, and old branch evidence are insufficient. This is a candidate until those exact-source tests and the unchanged dependency audit pass.

## Cipher work on the existing blocking executor

`cipher.rs` moves the owned `Secret` and previously read encrypted cipher into
Tokio's existing blocking executor. The four independent store opens can then
make progress concurrently without running passphrase KDFs on the async thread.
No new pool, key cache, dependency, encryption format, KDF parameter or startup
deadline is introduced. The original library-only fast test export branch is
preserved; integration and production builds still use the full-strength export.

The worker returns the cipher and, only for creation or legacy high-entropy
migration, an encrypted export. It has no SQLite connection. The original async
owner alone writes that export after a successful await. Cancellation while
waiting cannot cause a late crypto worker to write the database. Already
dispatched SQLite writes retain their original cancellation semantics, and a
started blocking task may finish after cancellation. Its owned `Secret` remains
zeroizing; temporary legacy base64 text is also zeroizing on all exit paths.

`CipherTask` distinguishes a worker join failure from the original `InitCipher`
crypto error. This change does not add same-database initialization locking or
CAS; the existing concurrent-open publication contract is unchanged. It also
does not claim physical CPU cost is reduced or that every host meets five seconds.
Exact-source restart and old-version migration qualification remain required.
