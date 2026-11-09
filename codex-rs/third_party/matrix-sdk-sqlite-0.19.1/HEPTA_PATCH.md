# Matrix SQLite 0.19.1 compatibility candidate

The official archive and upstream license are bound by HEPTA-PATCH-PROVENANCE.json. Only the two rusqlite constraints change from 0.40.2 to exactly 0.41.1, retaining upstream limits, fallible_uint and cache features. This shares libsqlite3-sys 0.39.1 with the separately provenance-bound SQLx 0.9.0 manifest compatibility patch, replacing the previous 0.37 link with bundled SQLite 3.54.1. All Rust implementation and SQL migration files remain byte-identical to the official crate.

This SDK upgrade performs real storage migrations: crypto state reaches version 19, state reaches version 16, and event cache reaches version 18 with upstream cache resets. Hepta retains the matrix-sdk-0.18 directory as its existing data identity, its human passphrase API, its own authoritative sync cursor/inbox/outbox, and its production five-second startup bound. Old SDK binaries must not reopen stores after migration; this change does not provide reverse migration or claim lossless binary rollback. Recovery requires an independently retained, consistent pre-upgrade store backup.

Native qualification must create encrypted stores and old Olm/Megolm ciphertext with the original 0.18 graph, then reopen through the candidate production API and decrypt with the existing persisted sessions. Same-version restart, matching public keys, a compilation pass, and old branch evidence are insufficient. This is a candidate until those exact-source tests and the unchanged dependency audit pass.

The original archive license entries remain byte-identical. Full upstream license texts are attached as `UPSTREAM-LICENSE`, fetched from the exact .cargo_vcs_info.json commit and SHA-256 bound in the provenance record.
